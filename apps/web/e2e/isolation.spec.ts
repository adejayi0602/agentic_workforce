import { expect, test } from "@playwright/test";

import { createOrganisation, createProject, projectKey, signIn, text, unique } from "./helpers";

test("another organisation's project is not reachable by link", async ({ browser }) => {
  // Two separate browser contexts: two people, two sessions.
  const alice = await (await browser.newContext()).newPage();
  const bob = await (await browser.newContext()).newPage();

  await signIn(alice, unique("alice"));
  await createOrganisation(alice, unique("Alice Org"));
  const projectUrl = await createProject(alice, "Confidential roadmap", projectKey());

  await signIn(bob, unique("bob"));
  await createOrganisation(bob, unique("Bob Org"));
  await bob.goto(projectUrl);
  await expect(bob.getByRole("heading", { name: "Project not found" })).toBeVisible();
  await expect(text(bob, "Confidential roadmap")).toHaveCount(0);

  // Bob's own project list doesn't include it either.
  await bob.goto("/projects");
  await bob.getByRole("button", { name: "All" }).click();
  await expect(text(bob, "No projects yet.")).toBeVisible();
});
