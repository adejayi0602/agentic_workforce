import { expect, type Page } from "@playwright/test";

/**
 * Next.js 16 keeps recently visited pages mounted but hidden, so label and text locators must
 * be limited to visible elements. Role locators already ignore hidden ones.
 */
export const field = (page: Page, label: string) =>
  page.getByLabel(label, { exact: true }).filter({ visible: true });

export const text = (page: Page, value: string | RegExp) =>
  page.getByText(value).filter({ visible: true });

export function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;
}

export function projectKey(): string {
  return `E${Date.now().toString(36).toUpperCase().slice(-6)}`.replace(/[^A-Z0-9]/g, "X");
}

export async function signIn(page: Page, username: string, displayName?: string, email?: string) {
  if (!page.url().endsWith("/sign-in")) await page.goto("/sign-in");
  await field(page, "Username").fill(username);
  if (displayName) await page.getByLabel(/Display name/).filter({ visible: true }).fill(displayName);
  if (email) await page.getByLabel(/^Email/).filter({ visible: true }).fill(email);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Signed in once the app leaves the sign-in page (it redirects as soon as the session is ready).
  await expect(page).not.toHaveURL(/\/sign-in$/);
}

export async function createOrganisation(page: Page, name: string) {
  await page.goto("/organisations/new");
  await field(page, "Name").fill(name);
  await page.getByRole("button", { name: "Create organisation" }).click();
  await expect(text(page, "You're signed in as")).toBeVisible();
}

export async function createProject(page: Page, name: string, key: string): Promise<string> {
  await page.goto("/projects/new");
  await field(page, "Name").fill(name);
  await field(page, "Key").fill(key);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: new RegExp(name) })).toBeVisible();
  return page.url();
}

export const API_URL = "http://localhost:8000";

/** The path of the newest invitation link "emailed" to `email` (dev-only mailbox). */
export async function invitationPath(page: Page, email: string): Promise<string> {
  let body = "";
  await expect
    .poll(async () => {
      const response = await page.request.get(`${API_URL}/api/v1/dev-auth/mail`, { params: { to: email } });
      const mail = (await response.json()) as { body: string }[];
      body = mail[0]?.body ?? "";
      return body.includes("#token=");
    })
    .toBe(true);
  const token = body.split("#token=")[1].split(/\s/)[0];
  return `/invitations/accept#token=${token}`;
}
