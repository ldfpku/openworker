// A new session is ONE draft (owner ask 2026-09-02): the setup row's picks re-target it on
// its existing id instead of replacing it, so the typed draft survives a folder pick, a
// coworker pick and a Settings round-trip; and mode bookkeeping is a SETTING, not history —
// it never ends the draft phase.
import { test, expect } from "./fixtures";

test("setup picks re-target the draft: the typed text survives folder and coworker", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByText("New session").first().click();

  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("precious draft");

  // Folder chip → native pick (mocked server-side → /tmp/picked-folder).
  await page.getByTestId("folder-chip").click();
  await page
    .locator(".setup-menu")
    .getByRole("button", { name: /Choose a(nother)? folder…/ })
    .click();
  await expect(page.getByTestId("folder-chip")).toContainText("picked-folder");
  await expect(box).toHaveValue("precious draft");

  // Coworker chip → the draft is re-targeted, not replaced.
  await page.getByTestId("coworker-chip").click();
  await page.locator(".setup-menu").getByRole("button", { name: /Security Coworker/ }).click();
  await expect(page.getByTestId("folder-chip")).toContainText("picked-folder");
  await expect(box).toHaveValue("precious draft");
});

test("a mode pick on a draft leaves no marker and keeps the setup row", async ({ page }) => {
  await page.goto("/");
  await page.getByText("New session").first().click();

  await expect(page.getByTestId("setup-row")).toBeVisible();
  await page.getByRole("button", { name: "Mode", exact: true }).click();
  await page.getByTestId("mode-menu").getByText("Bypass approvals", { exact: false }).first().click();

  // A setting, not activity: no transcript marker, and the draft phase is intact.
  await expect(page.locator(".main-scroll").getByText(/is on\./)).toHaveCount(0);
  await expect(page.getByTestId("setup-row")).toBeVisible();

  // The first message is what ends the draft — then the setup row leaves, as always.
  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("hello there");
  await box.press("Enter");
  await expect(page.getByText(/Echo: hello there/)).toBeVisible();
  await expect(page.getByTestId("setup-row")).toHaveCount(0);
});

test("a Settings round-trip gives the unsent draft back", async ({ page }) => {
  // Settings is another `surface` and unmounts the composer; the draft is kept in App and
  // restored on remount. Driven from a session that HAS a sidebar row — a never-saved draft
  // has no row to click, so the mock UI offers no way back to that same id.
  await page.goto("/");
  await page.getByText("Draft the launch note").first().click();

  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("half a thought");

  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByPlaceholder(/Ask the coworker/)).toHaveCount(0);

  await page.getByText("Draft the launch note").first().click();
  await expect(page.getByPlaceholder(/Ask the coworker/)).toHaveValue("half a thought");
});
