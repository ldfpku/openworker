import { test, expect } from "./fixtures";

// The company gateway's model list is an allowlist the administrator edits at any time.
// When the default model leaves it, the backend does NOT pick a replacement: /v1/settings
// answers `model_ready: false` + `model_notice: "default_model_gone"` and no longer lists
// the dead id. The composer must then say so and ask for a choice — not show the generic
// "connect a model" chip (a provider IS connected), and not keep offering the dead model.
const SETTINGS = {
  model: "aigw:anthropic/claude-sonnet-5",
  models: ["aigw:openai/gpt-6.1-sol"],
  model_labels: { "aigw:openai/gpt-6.1-sol": "GPT-6.1 Sol · via Cloudflare" },
  has_key: true,
  model_ready: false,
  model_notice: "default_model_gone",
  onboarded: true,
  nav_layout: "flat",
};

test("a default that left the gateway list asks for a choice instead of being replaced", async ({
  page,
}) => {
  await page.route("**/v1/settings", (r) =>
    r.request().method() === "GET" ? r.fulfill({ json: SETTINGS }) : r.fallback(),
  );
  await page.goto("/");
  const notice = page.getByTestId("model-default-gone");
  await expect(notice).toBeVisible();
  await expect(notice).toHaveAttribute("role", "alert");
  await expect(notice).toContainText("no longer on your available list");
  // The chip names the action (choose), not the generic "connect a model".
  await expect(page.locator(".pill-label").filter({ hasText: "Choose a model" })).toBeVisible();
  // The dead default is not offered anywhere on the composer.
  await expect(page.getByText("claude-sonnet-5")).toHaveCount(0);
});
