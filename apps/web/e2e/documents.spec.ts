import { expect, test } from "@playwright/test";

import { createOrganisation, createProject, projectKey, signIn, text, unique } from "./helpers";

// The standard antivirus test string. Harmless; every scanner flags it.
const EICAR = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*";

const SRS = `# Payments SRS

## 3 Functional requirements

### 3.2 Card payments

REQ-PAY-014: The system shall refund card payments within 5 working days.

| ID | Priority |
| --- | --- |
| REQ-PAY-014 | Critical |
`;

async function upload(page: import("@playwright/test").Page, name: string, content: string) {
  await page.getByRole("button", { name: "Upload a document" }).click();
  await page.getByLabel("File", { exact: true }).filter({ visible: true }).setInputFiles({
    name,
    mimeType: "text/markdown",
    buffer: Buffer.from(content),
  });
  await page.getByRole("button", { name: new RegExp(`^Upload ${name.replace(".", "\\.")}`) }).click();
}

test.describe("Document intake", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, unique("docs"));
    await createOrganisation(page, unique("Docs Org"));
    await createProject(page, "Payments platform", projectKey());
  });

  test("upload an SRS, watch it process, and review it with locations", async ({ page }) => {
    await upload(page, "payments-srs.md", SRS);
    const row = page.getByRole("row").filter({ hasText: "payments-srs" });
    await expect(row).toBeVisible();
    await expect(row.getByText("Ready to review")).toBeVisible({ timeout: 60_000 });

    await row.getByRole("link", { name: "payments-srs" }).click();
    await page.getByRole("link", { name: "Review extracted content" }).click();

    await expect(page.getByRole("heading", { name: "payments-srs.md" })).toBeVisible();
    const requirement = page.getByRole("listitem").filter({ hasText: "REQ-PAY-014: The system shall refund" });
    await expect(requirement).toContainText("Payments SRS › 3 Functional requirements › 3.2 Card payments");
    await expect(page.getByRole("cell", { name: "Critical" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Outline" }).getByText("3.2 Card payments")).toBeVisible();

    await page.getByLabel("Search this document").fill("no-such-text");
    await expect(text(page, "No matches.")).toBeVisible();
  });

  test("an infected file is quarantined and explained", async ({ page }) => {
    await upload(page, "notes.md", `# Notes\n\n${EICAR}\n`);
    const row = page.getByRole("row").filter({ hasText: "notes" });
    await expect(row.getByText("Quarantined")).toBeVisible({ timeout: 60_000 });
    await row.getByRole("link", { name: "notes" }).click();
    await expect(text(page, /Our malware scan flagged this file/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Review extracted content" })).toHaveCount(0);
  });

  test("legacy Word files are refused before upload, with advice", async ({ page }) => {
    await page.getByRole("button", { name: "Upload a document" }).click();
    await page.getByLabel("File", { exact: true }).filter({ visible: true }).setInputFiles({
      name: "old-srs.doc",
      mimeType: "application/msword",
      buffer: Buffer.from("legacy"),
    });
    await expect(text(page, /save it as \.docx/)).toBeVisible();
    await expect(page.getByRole("button", { name: /^Upload old-srs\.doc/ })).toBeDisabled();
  });
});
