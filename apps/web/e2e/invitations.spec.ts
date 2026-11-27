import { expect, test } from "@playwright/test";

import { createOrganisation, field, invitationPath, signIn, text, unique } from "./helpers";

/**
 * #11: an admin invites someone with a role; they open the link signed out, sign in with the
 * invited address, accept, and get exactly that role's permissions.
 */
test("invite an auditor, who joins read-only", async ({ page }) => {
  const orgName = unique("Invites");
  const auditor = unique("auditor");
  const auditorEmail = `${auditor}@example.com`;

  await test.step("admin invites by email with a role", async () => {
    await signIn(page, unique("admin"), "Invite Admin");
    await createOrganisation(page, orgName);
    await page.getByRole("link", { name: "Members" }).click();
    await field(page, "Email address").fill(auditorEmail);
    await field(page, "Role").selectOption("auditor");
    await page.getByRole("button", { name: "Send invitation" }).click();
    await expect(text(page, `Invitation sent to ${auditorEmail}.`)).toBeVisible();
    await expect(page.getByRole("cell", { name: auditorEmail, exact: true })).toBeVisible();
    await expect(text(page, "Waiting")).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();
  });

  const link = await invitationPath(page, auditorEmail);

  await test.step("the link survives signing in", async () => {
    await page.goto(link);
    await expect(page).toHaveURL(/\/sign-in$/);
    await signIn(page, auditor, "Audrey Auditor", auditorEmail);
    await expect(page).toHaveURL(/\/invitations\/accept$/); // token removed from the address bar
    await expect(text(page, orgName)).toBeVisible();
    await expect(text(page, /as auditor/)).toBeVisible();
  });

  await test.step("accept and get the auditor's permissions only", async () => {
    await page.getByRole("button", { name: "Accept invitation" }).click();
    await expect(text(page, "You're signed in as")).toBeVisible();
    await page.getByRole("link", { name: "Projects", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
    await expect(page.getByRole("link", { name: "New project" })).toHaveCount(0);
    await page.getByRole("link", { name: "Members" }).click();
    await expect(text(page, "Audrey Auditor")).toBeVisible();
    await expect(page.getByRole("button", { name: "Send invitation" })).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: /^Role for/ })).toHaveCount(0); // cannot change roles
  });

  await test.step("the link only works once", async () => {
    await page.goto(link);
    await expect(text(page, "This invitation has already been used.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Accept invitation" })).toHaveCount(0);
  });
});
