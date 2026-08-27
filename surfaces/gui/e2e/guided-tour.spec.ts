// First-run guided tour: fixtures.ts marks every spec's device as "tour seen" so the
// overlay never intercepts unrelated clicks — this spec is the one place that clears the
// flag (its init script runs AFTER mockApi's, so the remove wins) and pins the real
// first-run behavior: auto-open, step order, and done-once persistence across reloads.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

test("first run walks the five anchors once; a reload stays quiet", async ({ page }) => {
  // Clear the flag ONCE (a marker guards it): init scripts re-run on reload, and an
  // unconditional remove would wipe the finish-time flag and resurrect the tour.
  await page.addInitScript(() => {
    try {
      if (!localStorage.getItem("ocw-e2e-tour-cleared")) {
        localStorage.setItem("ocw-e2e-tour-cleared", "1");
        localStorage.removeItem("coworker:tour-done:v1");
      }
    } catch {
      /* ignore */
    }
  });
  await page.goto("/");

  const card = page.getByTestId("tour-card");
  await expect(card).toBeVisible();
  await expect(card).toContainText("Start here");

  const next = page.getByTestId("tour-next");
  await next.click();
  await expect(card).toContainText("Hand over the work");
  await next.click();
  await expect(card).toContainText("Pick a model");
  await next.click();
  await expect(card).toContainText("Coworker and folder");
  await next.click();
  await expect(card).toContainText("Experts, skills and settings");
  await expect(next).toHaveText("Done");
  await next.click();
  await expect(card).toHaveCount(0);

  // Finishing persists: on reload the marker keeps the init script from clearing the
  // flag the finish wrote, so the tour must stay gone.
  await page.reload();
  await expect(page.getByTestId("setup-row")).toBeVisible();
  await expect(page.getByTestId("tour-card")).toHaveCount(0);
});

test("Skip tour dismisses it for good", async ({ page }) => {
  await page.addInitScript(() => {
    try {
      localStorage.removeItem("coworker:tour-done:v1");
    } catch {
      /* ignore */
    }
  });
  await page.goto("/");
  await expect(page.getByTestId("tour-card")).toBeVisible();
  await page.getByTestId("tour-skip").click();
  await expect(page.getByTestId("tour-card")).toHaveCount(0);
});
