import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests: the real API (against PostgreSQL) and the production web build.
 *
 * Prerequisites: PostgreSQL running and migrated (`make up && make migrate` locally; CI does
 * this itself). Playwright starts the API and the web server.
 *
 * Set PLAYWRIGHT_CHROMIUM_EXECUTABLE to use an installed Chrome instead of Playwright's own.
 */

const API_PORT = 8000;
const WEB_PORT = 3000;
const repoRoot = path.resolve(__dirname, "../..");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
          ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
          : {},
      },
    },
  ],
  webServer: [
    {
      command: `uv run --package workforce-api uvicorn workforce_api.main:app --port ${API_PORT}`,
      cwd: repoRoot,
      url: `http://localhost:${API_PORT}/api/v1/health/ready`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        WORKFORCE_ENV: "test",
        WORKFORCE_ORGANISATION_CREATION: "open",
        WORKFORCE_CORS_ORIGINS: `["http://localhost:${WEB_PORT}"]`,
        ...(process.env.E2E_DATABASE_URL ? { WORKFORCE_DATABASE_URL: process.env.E2E_DATABASE_URL } : {}),
        ...(process.env.E2E_S3_ENDPOINT_URL ? { WORKFORCE_S3_ENDPOINT_URL: process.env.E2E_S3_ENDPOINT_URL } : {}),
      },
    },
    {
      command: `npx next start -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/sign-in`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
