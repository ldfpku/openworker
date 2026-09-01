// Start-screen template tasks (§27): three concrete rows, no icon tiles, no "Set me up" list.
// Sub-lines are outcome-voiced; connection state lives in the dots + the trailing action.
// Two folder-driven rows (folder analysis, downtime analysis) share the pick-folder mechanism;
// the weekly-report-to-WeChat row is gated on the weixin connector — "Configure ›" expands the
// rail's Access section (§32); ready row → click prefills the composer with the template stem.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

test("three rows, no Set-me-up; the gated row shows Configure › and expands the rail's Access section", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("What should we produce?")).toBeVisible();

  // Exactly the three template tasks; the old setup list is gone.
  await expect(page.locator(".task-card")).toHaveCount(3);
  await expect(page.getByText("Set me up (optional)")).toHaveCount(0);
  await expect(page.getByText("Give me access to a folder")).toHaveCount(0);

  // Fixture session state: slack + github live, weixin not → the weekly-report row is gated,
  // with the Configure affordance visible AT REST (no hover needed — it IS the row's action).
  const wk = page.getByTestId("intro-task-weekly");
  await expect(wk).toContainText("Configure ›");
  await expect(wk.locator(".task-card-act")).toHaveCSS("opacity", "1");

  // Sub-lines describe the task's outcome, never connection state.
  await expect(wk).toContainText("Summarize the week's progress and issues, sent every Friday");
  await expect(wk).not.toContainText(/connect/i);

  // Configure → the rail's Access section expands (§32), not a bespoke setup surface.
  await wk.click();
  await expect(page.getByRole("region", { name: "Session access" })).toBeVisible();
  // No composer prefill happened on the gated click.
  await expect(page.getByPlaceholder(/Ask the coworker/)).toHaveValue("");
});

test("ready weekly-report row reveals Start → on hover and prefills the composer", async ({ page }) => {
  // Make weixin live for this session (registered after the fixture's routes → wins).
  await page.route("**/v1/sessions/*/connections*", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        connected: [
          { connector: "github", enabled: true, detail: "" },
          { connector: "slack", enabled: true, detail: "" },
          { connector: "weixin", enabled: true, detail: "" },
        ],
        recommended: [],
        attention: 0,
      }),
    }),
  );
  await page.goto("/");

  const wk = page.getByTestId("intro-task-weekly");
  await expect(wk).toContainText("Start →");
  // The action is hover-revealed on ready rows (hidden at rest).
  await expect(wk.locator(".task-card-act")).toHaveCSS("opacity", "0");
  await wk.hover();
  await expect(wk.locator(".task-card-act")).toHaveCSS("opacity", "1");

  await wk.click();
  await expect(page.getByPlaceholder(/Ask the coworker/)).toHaveValue(/weekly production report/);
});

test("folder task opens the inline add-folder form; adding a folder prefills the composer", async ({
  page,
}) => {
  await page.goto("/");

  // No shared folder yet (the fixture root is the primary scratch) → the row expands the form.
  await page.getByTestId("intro-task-folder").click();
  const path = page.getByPlaceholder("Choose or paste a folder path…");
  await expect(path).toBeVisible();
  await path.fill("/Users/me/Reports");
  await page.getByRole("button", { name: "Add", exact: true }).click();

  await expect(page.getByPlaceholder(/Ask the coworker/)).toHaveValue(
    /Analyze the files in this folder/,
  );
});

test("downtime task shares the folder mechanism and prefills its own prompt", async ({ page }) => {
  await page.goto("/");

  // No shared folder yet → the downtime row expands the same inline form as the folder row.
  await page.getByTestId("intro-task-downtime").click();
  const path = page.getByPlaceholder("Choose or paste a folder path…");
  await expect(path).toBeVisible();
  await path.fill("/Users/me/Maintenance");
  await page.getByRole("button", { name: "Add", exact: true }).click();

  // The downtime row's own prompt fires, not the folder row's.
  await expect(page.getByPlaceholder(/Ask the coworker/)).toHaveValue(
    /equipment logs and downtime\/repair records/,
  );
});
