// §8.4 breaker surfacing (owner ask 2026-08-24): when the Auto-Approve reviewer pauses
// itself after 5 straight denials, the transcript gets a notice AND the composer's mode
// chip says "· paused" — quietly, until the turn ends or an ask_user answer resets it.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

test("reviewer pause shows a transcript notice and marks the mode chip", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Draft the launch note").first().click();

  // Switch the session into Auto-approve (entry gated on the settings flag).
  await page.getByRole("button", { name: "Mode", exact: true }).click();
  await page.getByTestId("mode-menu").getByText("Auto-approve").click();

  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("trip the reviewer");
  await box.press("Enter");

  // The tripping deny carries the pause: notice inline, "· paused" on the chip.
  await expect(page.getByText(/Auto-approve is paused for the rest of this turn/)).toBeVisible();
  await expect(page.getByTestId("mode-paused")).toBeVisible();
  await expect(page.getByRole("button", { name: "Mode", exact: true })).toContainText("paused");
});

test("an unsure escalation shows the reviewer's hesitation on the card", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Draft the launch note").first().click();
  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("run an unsure tool");
  await box.press("Enter");

  const note = page.getByTestId("approval-reviewer-unsure");
  await expect(note).toBeVisible();
  await expect(note).toContainText("reviewer wasn\u2019t sure: This runs a newly created script");
});

test("mode notices: full explainer once, one-line markers after", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Draft the launch note").first().click();

  const pickMode = async (label: string) => {
    await page.getByRole("button", { name: "Mode", exact: true }).click();
    await page.getByTestId("mode-menu").getByText(label, { exact: false }).first().click();
  };

  // A DRAFT's mode is a setting, not history (owner ask 2026-09-02) — markers only start
  // once the conversation has: send a turn first.
  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("hello there");
  await box.press("Enter");
  await expect(page.getByText(/Echo: hello there/)).toBeVisible();

  // First entry into Auto-approve: the full (new, shorter) explainer.
  await pickMode("Auto-approve");
  await expect(page.getByText("Auto-approve is on.")).toBeVisible();
  await expect(
    page.getByText(/uses a model to let routine actions through without asking/),
  ).toBeVisible();

  // Later switches: one-line markers only — the banner never repeats.
  await pickMode("Ask for approval");
  await expect(page.getByText("Ask for approval is on.")).toBeVisible();
  // The marker names the mode the user picked. The server builds it from the CANONICAL value
  // it just applied, so a client that sent the legacy "auto" got a marker reading the raw wire
  // id back (audit 2026-09-13).
  await pickMode("Bypass approvals");
  await expect(page.getByText("Bypass approvals is on.")).toBeVisible();
  await expect(page.locator(".main-scroll").getByText(/^auto is on\.$/)).toHaveCount(0);
  await pickMode("Auto-approve");
  await expect(page.getByText("Auto-approve is on.")).toHaveCount(2); // title + marker
  await expect(
    page.getByText(/uses a model to let routine actions through without asking/),
  ).toHaveCount(1);
});
