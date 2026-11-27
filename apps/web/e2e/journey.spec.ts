import { expect, test } from "@playwright/test";

import { createOrganisation, field, projectKey, signIn, text, unique } from "./helpers";

test.describe("Sprint 1 journey", () => {
  test("sign in, organisation, project lifecycle, members, audit, sign out", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    page.on("pageerror", (e) => errors.push(String(e)));

    await test.step("signed-out visitors are sent to sign-in", async () => {
      await page.goto("/projects");
      await expect(page).toHaveURL(/\/sign-in$/);
    });

    await test.step("sign in and see the empty state", async () => {
      await signIn(page, unique("e2e"), "E2E Admin");
      await expect(page.getByRole("heading", { name: "No organisation yet" })).toBeVisible();
    });

    await test.step("create an organisation", async () => {
      await createOrganisation(page, unique("Acme"));
      await expect(text(page, /API .* is ready/)).toBeVisible();
    });

    const key = projectKey();
    await test.step("create a project (key is upper-cased by the form)", async () => {
      await page.getByRole("link", { name: "Projects", exact: true }).click();
      await expect(text(page, "No active projects yet.")).toBeVisible();
      await page.getByRole("link", { name: "New project" }).click();
      await field(page, "Name").fill("Payments platform");
      await field(page, "Key").fill(key.toLowerCase());
      await page.getByRole("button", { name: "Create project" }).click();
      await expect(page.getByRole("heading", { name: /Payments platform/ })).toBeVisible();
    });

    await test.step("edit and archive, with history", async () => {
      await page.getByRole("button", { name: "Edit" }).click();
      await field(page, "Name").fill("Payments platform v2");
      await page.getByRole("button", { name: "Save" }).click();
      await expect(page.getByRole("heading", { name: /Payments platform v2/ })).toBeVisible();
      await page.getByRole("button", { name: "Archive" }).click();
      await expect(page.getByRole("button", { name: "Restore" })).toBeVisible();
      await expect(text(page, "Project archive")).toBeVisible();
      await expect(text(page, "Project update")).toBeVisible();
    });

    await test.step("filters, members and audit", async () => {
      await page.getByRole("link", { name: "Projects", exact: true }).click();
      await page.getByRole("button", { name: "Archived" }).click();
      await expect(page.getByRole("link", { name: "Payments platform v2" })).toBeVisible();
      await page.getByRole("link", { name: "Members" }).click();
      await expect(text(page, "(you)")).toBeVisible();
      await page.getByRole("link", { name: "Audit" }).click();
      await expect(text(page, "Organisation create")).toBeVisible();
    });

    await test.step("mobile layout has no horizontal overflow", async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.getByRole("link", { name: "Projects", exact: true }).click();
      await page.getByRole("button", { name: "All" }).click();
      await expect(page.getByRole("link", { name: "Payments platform v2" })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      expect(overflow).toBe(false);
      await page.setViewportSize({ width: 1280, height: 860 });
    });

    await test.step("sign out", async () => {
      await page.getByRole("button", { name: "Sign out" }).click();
      await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    });

    expect(errors, "browser console errors").toEqual([]);
  });
});
