// Auto-compaction GUI: the Settings card is now READ-ONLY — the trigger ratio is a fixed
// industry default and the context window is read from the model's metadata, so there are
// no editable threshold/cap inputs and the card never POSTs. The fixed Cloudflare summarizer
// pool is explained, and the "context compacted" divider renders inline mid-session without
// touching the transcript.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

test("Settings: Context compaction card is read-only (fixed ratio, metadata window)", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Context optimization", exact: true }).click();

  const card = page.getByTestId("compaction-card");
  await expect(card).toBeVisible();
  await expect(card.getByText("Context compaction")).toBeVisible();

  // The fixed ratio is shown read-only (default 80% when the backend sends no override).
  const readonly = card.getByTestId("compaction-threshold-readonly");
  await expect(readonly).toBeVisible();
  await expect(readonly).toContainText("80");

  // The old editable inputs are gone entirely — nothing to type into.
  await expect(card.getByTestId("compaction-threshold")).toHaveCount(0);
  await expect(card.getByTestId("compaction-cap")).toHaveCount(0);

  // A read-only card never POSTs to the compaction settings endpoint.
  let posted = false;
  page.on("request", (r) => {
    if (r.url().endsWith("/v1/settings/compaction") && r.method() === "POST") posted = true;
  });

  // Self-managed sessions use the fixed Cloudflare pool; no legacy model picker remains.
  await expect(card.getByTestId("compaction-model")).toHaveCount(0);
  await expect(
    card.getByText(
      "Self-managed sessions automatically summarize through Cloudflare AI Gateway with failover: GPT-6 Luna → GLM 5.3 Flash → Claude Haiku 5.5. No summarizer model setting is needed.",
    ),
  ).toBeVisible();

  // Give any stray POST a beat to fire, then assert none did.
  await page.waitForTimeout(300);
  expect(posted).toBe(false);
});

test("the compacted divider renders mid-session and the transcript stays intact", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByText("Draft the launch note").first().click();
  const box = page.getByPlaceholder(/Ask the coworker/);

  // An earlier exchange that must survive the compaction marker (transcript intact).
  await box.fill("remember the launch date");
  await box.press("Enter");
  await expect(page.getByText("Echo: remember the launch date").first()).toBeVisible({
    timeout: 10_000,
  });

  await box.fill("compact the context");
  await box.press("Enter");
  // The transient signal shows while the summarizer runs, then yields to the divider.
  await expect(page.getByText("Compacting context…").first()).toBeVisible({
    timeout: 10_000,
  });
  await expect(
    page.getByText("Context compacted — earlier turns were summarized").first(),
  ).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Compacting context…")).toHaveCount(0);
  await expect(
    page.getByText("Still on it — continuing where I left off.").first(),
  ).toBeVisible();
  // Outbound-only: everything before the divider is still on screen.
  await expect(page.getByText("Echo: remember the launch date").first()).toBeVisible();
});
