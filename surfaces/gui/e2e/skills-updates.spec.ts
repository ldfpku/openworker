import { test, expect } from "./fixtures";

// 来源与升级 §1–§7 journey — Settings ▸ Skills: switch on an external source, its skills
// appear read-only and manual; a check finds updates (the stale cache triggers it in the
// background); a plain update is ticked by default, the locally changed one is not; ticking
// it asks for confirmation; upgrading shows results; rollback restores. Hermetic: every
// /v1 call lands in fixtures.ts.

const openSkills = async (page: import("@playwright/test").Page) => {
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Skills", exact: true }).click();
};

test("skills-updates: source on → external rows → check → confirm → upgrade → roll back", async ({ page }) => {
  await openSkills(page);

  // Sources start off; nothing external is listed yet.
  const sources = page.getByTestId("skill-sources");
  const shared = sources.getByRole("switch", { name: /Use skills from Shared folder/ });
  await expect(shared).toHaveAttribute("aria-checked", "false");
  await expect(sources.getByTestId("source-codex")).toContainText("Not found");
  await expect(page.getByTestId("skill-row-external:pretty-mermaid")).toHaveCount(0);

  await shared.click();
  const mermaid = page.getByTestId("skill-row-external:pretty-mermaid");
  await expect(mermaid).toBeVisible();
  await expect(mermaid).toContainText("Read-only");
  await expect(mermaid.getByRole("radio", { name: "Manual" })).toHaveAttribute("aria-checked", "true");
  await expect(mermaid.getByTitle("Edit", { exact: true })).toHaveCount(0);

  // Check for updates (explicitly; the background check covers a reload).
  await page.getByTestId("check-updates").click();
  await expect(mermaid.getByTestId("update-status")).toHaveText("Update available");
  const pdf = page.getByTestId("skill-row-external:pdf-translate");
  await expect(pdf.getByTestId("update-status")).toHaveText("Update · changed locally");
  await expect(pdf).toContainText("Local changes: 改动 SKILL.md");

  // Default selection: the plain update only.
  await expect(page.getByRole("checkbox", { name: /pretty-mermaid/ })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /pdf-translate/ })).not.toBeChecked();
  await expect(page.getByTestId("upgrade-bar")).toContainText("1 selected");

  // Ticking the changed one asks first.
  await page.getByRole("checkbox", { name: /pdf-translate/ }).check();
  await page.getByRole("button", { name: "Upgrade selected" }).click();
  await expect(page.getByTestId("confirm-modified")).toContainText("pdf-translate");
  await page.getByRole("button", { name: "Upgrade anyway" }).click();

  const results = page.getByTestId("upgrade-results");
  await expect(results).toContainText("pretty-mermaid upgraded");
  await expect(results).toContainText("pdf-translate upgraded");
  await expect(mermaid.getByTestId("update-status")).toHaveText("Up to date");
  await expect(page.getByTestId("upgrade-bar")).toHaveCount(0);

  // Roll back one.
  await mermaid.getByRole("button", { name: "Roll back" }).click();
  await expect(page.getByRole("status")).toContainText("rolled back");
  await expect(mermaid.getByTestId("update-status")).toHaveText("Update available");
});

test("skills-updates: switching an external skill to auto", async ({ page }) => {
  await openSkills(page);
  await page.getByTestId("skill-sources").getByRole("switch", { name: /Use skills from Shared folder/ }).click();
  const mermaid = page.getByTestId("skill-row-external:pretty-mermaid");
  await mermaid.getByRole("radio", { name: "Auto" }).click();
  await expect(page.getByRole("status")).toContainText("is now automatic");
  await expect(mermaid.getByRole("radio", { name: "Auto" })).toHaveAttribute("aria-checked", "true");
});
