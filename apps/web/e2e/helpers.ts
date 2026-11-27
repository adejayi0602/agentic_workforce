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

export async function signIn(page: Page, username: string, displayName?: string) {
  await page.goto("/sign-in");
  await field(page, "Username").fill(username);
  if (displayName) await page.getByLabel(/Display name/).filter({ visible: true }).fill(displayName);
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
