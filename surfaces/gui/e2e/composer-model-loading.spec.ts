import { test, expect } from "./fixtures";

// The composer must never advertise models the backend didn't confirm: before the
// /v1/settings list arrives (cold app boot races the sidecar), the picker is a busy
// "Loading models…" chip — NOT a hardcoded fallback list, which went stale and offered
// phantom ids (caught by owner, 2026-07-21).
test("picker shows a busy Loading-models chip until the list arrives", async ({ page }) => {
  await page.route("**/v1/settings", (r) =>
    r.fulfill({
      json: { model: "gpt-5.5", models: [], model_labels: {}, has_key: true, model_ready: true, onboarded: true, nav_layout: "flat" },
    }),
  );
  await page.goto("/");
  const chip = page.getByTestId("models-loading");
  await expect(chip).toBeVisible();
  await expect(chip).toHaveAttribute("aria-busy", "true");
  await expect(chip).toContainText("Loading models…");
  await expect(page.locator(".dd-menu")).toHaveCount(0);
});

// A click on that placeholder is a real intent to open the picker. On a cold packaged-app
// boot the list trails the UI reveal by a beat and the placeholder looked like the live chip,
// so the first click "did nothing" and only the second opened (owner-hit 2026-09-03). The
// click is kept and the picker opens by itself once the list lands.
test("a click on the Loading-models chip opens the picker once the list arrives", async ({
  page,
}) => {
  let release: () => void = () => {};
  const held = new Promise<void>((r) => (release = r));
  await page.route("**/v1/settings", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await held;
    await route.fallback();
  });
  await page.goto("/");
  const chip = page.getByTestId("models-loading");
  await expect(chip).toBeVisible();
  await chip.click();
  await expect(page.locator(".dd-menu")).toHaveCount(0);
  release();
  await expect(page.locator(".dd-menu")).toBeVisible();
  await expect(page.locator(".dd-item").filter({ hasText: "GPT-5.5" })).toBeVisible();
});
