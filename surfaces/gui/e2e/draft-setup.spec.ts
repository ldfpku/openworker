// A new session is ONE draft (owner ask 2026-09-02): the setup row's picks re-target it on
// its existing id instead of replacing it, so the typed draft survives a folder pick, a
// coworker pick and a Settings round-trip; and mode bookkeeping is a SETTING, not history —
// it never ends the draft phase.
import { test, expect } from "./fixtures";

// A personas payload where the general OpenWorker is NOT the default — an expert holds the
// pointer (C1: the baseline stays ENABLED whatever else is true, and is what every fallback
// lands on). `cowork` carries whatever `enabled` the caller passes: `false` is the stale-prefs
// state the server now self-heals, and the client must not act on it either.
const expertDefaultPersonas = (coworkEnabled: boolean) => ({
  internal: true,
  personas: [
    {
      id: "cowork", name: "OpenWorker", icon: "cowork",
      tagline: "Produce a deliverable — research, analysis, scripts",
      requires_folder: false, builtin: true, tools: ["files", "search"],
      enabled: coworkEnabled, surfaced: true, default: false, ships: true, group: "general",
    },
    {
      id: "security", name: "Security Coworker", icon: "shield",
      tagline: "Find and fix security issues — scan, triage, PR",
      requires_folder: true, builtin: true, tools: ["code_files", "git"],
      enabled: true, surfaced: true, default: true, ships: true, group: "security",
    },
  ],
});

const servePersonas = (page: import("@playwright/test").Page, coworkEnabled: boolean) =>
  page.route("**/v1/personas", (route) => route.fulfill({ json: expertDefaultPersonas(coworkEnabled) }));

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
  const modeChip = page.getByRole("button", { name: "Mode", exact: true });
  await modeChip.click();
  await page.getByTestId("mode-menu").getByText("Bypass approvals", { exact: false }).first().click();

  // A setting, not activity: no transcript marker, and the draft phase is intact.
  await expect(page.locator(".main-scroll").getByText(/is on\./)).toHaveCount(0);
  await expect(page.getByTestId("setup-row")).toBeVisible();
  await expect(modeChip).toContainText("Bypass approvals");

  // …and it SURVIVES the re-targets. Each setup pick bumps `connectNonce`, and every new
  // socket opens with a `ready` reporting the engine's mode — in the server's canonical
  // vocabulary. The client used to send (and match on) the legacy "auto", so the reconnect's
  // canonical value matched no picker row and the chip fell back to printing the raw wire id;
  // the reconciliation added for it must never revert a pick either (C4/C6, audit 2026-09-13).
  await page.getByTestId("folder-chip").click();
  await page
    .locator(".setup-menu")
    .getByRole("button", { name: /Choose a(nother)? folder…/ })
    .click();
  await expect(page.getByTestId("folder-chip")).toContainText("picked-folder");
  await expect(modeChip).toContainText("Bypass approvals");

  await page.getByTestId("coworker-chip").click();
  await page.locator(".setup-menu").getByRole("button", { name: /Security Coworker/ }).click();
  await expect(page.getByTestId("coworker-chip")).toContainText("Security Coworker");
  await expect(modeChip).toContainText("Bypass approvals");
  await expect(modeChip).not.toContainText("bypass-approvals"); // never the raw id
  await expect(page.locator(".main-scroll").getByText(/is on\./)).toHaveCount(0);

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

// The model half of the same rule. The server acknowledges EVERY applied model (C3) — but a
// draft's bind carries no `text`, because `text` is the persisted transcript marker and a
// model picked before the first message is a setting, not history. The client used to write a
// notice on any `model_changed` at all, which put a line into a conversation that had not
// started yet (owner ask 2026-09-02; audit 2026-09-13).
test("a model pick on a draft is acknowledged but leaves no marker", async ({ page }) => {
  await page.goto("/");
  await page.getByText("New session").first().click();

  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("precious draft");
  const picker = page.locator(".dd").filter({ hasText: "Claude Opus 4.8" });
  await picker.locator(".pill").click();
  await page.locator(".dd-item").filter({ hasText: "GPT-5.5" }).click();

  // The chip took the pick, the transcript stayed empty, the draft phase is intact.
  await expect(page.locator(".dd").filter({ hasText: "GPT-5.5" })).toBeVisible();
  await expect(page.locator(".main-scroll").getByText(/Model switched/)).toHaveCount(0);
  await expect(page.getByTestId("setup-row")).toBeVisible();
  await expect(box).toHaveValue("precious draft");

  // …and the pick rides the first message, as the model-per-message contract requires.
  await box.press("Enter");
  await expect(page.getByText("[model=gpt-5.5]", { exact: false }).first()).toBeVisible();
});

// P3: switching the specialist OFF lands on the BASELINE coworker — and stays there. The
// switch-off re-targets the draft, and the reconnect that follows is where a repair effect
// would get its chance to bounce the specialist back on.
test("switching the specialist off lands on the general coworker and stays off", async ({
  page,
}) => {
  await servePersonas(page, true); // baseline enabled, an expert holds the default pointer
  await page.goto("/");
  await page.getByText("New session").first().click();

  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("precious draft");
  const chip = page.getByTestId("coworker-chip");
  await chip.click();
  await page.locator(".setup-menu").getByRole("button", { name: /Security Coworker/ }).click();
  await expect(chip).toContainText("Security Coworker");

  // Off — the switch itself re-targets the draft to the general coworker.
  await chip.click();
  const sw = page.getByRole("switch", { name: "Use a specialist coworker" });
  await expect(sw).toBeChecked();
  await sw.click();
  await expect(chip).toContainText("OpenWorker (general)");
  await expect(sw).not.toBeChecked();

  // The re-target's reconnect lands about here; a bounce would arrive with it.
  await page.waitForTimeout(500);
  await expect(sw).not.toBeChecked();
  await expect(chip).toContainText("OpenWorker (general)");
  await expect(box).toHaveValue("precious draft"); // re-targeted, never resumed over
});

// …even when prefs claim the baseline is disabled. That state is stale, not a fact (the
// server self-heals it on load, C1): the client half must agree, or the repair effect reads
// "cowork is off" and switches straight back to the enabled default — which is exactly what
// bounced the switch back on every launch before this audit. The old repair also went through
// `switchAgent`, which resumes a stored conversation over the top of the draft being typed.
test("a stale disabled baseline never bounces the specialist switch back on", async ({
  page,
}) => {
  await servePersonas(page, false);
  await page.goto("/");
  await page.getByText("New session").first().click();

  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("precious draft");
  const chip = page.getByTestId("coworker-chip");
  await chip.click();
  await page.locator(".setup-menu").getByRole("button", { name: /Security Coworker/ }).click();
  await expect(chip).toContainText("Security Coworker");

  await chip.click();
  const sw = page.getByRole("switch", { name: "Use a specialist coworker" });
  await sw.click();
  await expect(chip).toContainText("OpenWorker (general)");

  await page.waitForTimeout(500);
  await expect(sw).not.toBeChecked();
  await expect(chip).toContainText("OpenWorker (general)");
  await expect(box).toHaveValue("precious draft");
});
