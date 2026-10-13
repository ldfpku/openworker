import { expect } from "@playwright/test";
import { test } from "./fixtures";

// Settings ▸ Models ▸ Vertex AI (owner-hit 2026-10-14): the command chip copied without
// saying so, and Test & save "did nothing" — its only feedback was one English line below
// the card. Now the chip confirms the copy, an empty required field is named and marked
// on the spot (no round trip), and a backend failure shows beside the button.
const VERTEX = {
  name: "vertex",
  title: "Vertex AI (Google Cloud)",
  needs_key: true,
  configured: false,
  auth: "key",
  values: {},
  suggested_models: [],
  recommended_model: null,
  fields: [
    { key: "project", label: "GCP project ID", secret: false, required: true, help: "", placeholder: "my-project-123" },
    { key: "location", label: "Location", secret: false, required: true, help: "", placeholder: "global", default: "global" },
    {
      key: "auth_method",
      label: "Connect with",
      secret: false,
      required: false,
      help: "",
      placeholder: "",
      default: "adc",
      choices: [
        {
          value: "adc",
          label: "Google Cloud login",
          tag: "Recommended",
          desc: "Uses your machine's Google Cloud identity (Application Default Credentials).",
          command: "gcloud auth application-default login",
        },
        { value: "api_key", label: "API key" },
      ],
    },
    { key: "vertex_api_key", label: "Vertex API key", secret: true, required: false, help: "", placeholder: "", show_when: { auth_method: "api_key" } },
  ],
};

async function openVertex(page) {
  await page.route("**/v1/providers", async (route) => {
    // The shared fixture list has no cloud provider with a command chip; this spec brings
    // its own (mirrors the backend's vertex descriptor).
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({ json: [VERTEX] });
  });
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Models", exact: true }).click();
  await page.getByTestId("set-provider-vertex").click();
}

test("the command chip confirms the copy", async ({ page }) => {
  // A stand-in clipboard: WebKit refuses writeText without a permission Playwright cannot
  // grant there, and what is under test is the confirmation, not the browser's clipboard.
  await page.addInitScript(() => {
    const w = window as unknown as { __copied: string[] };
    w.__copied = [];
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (text: string) => void w.__copied.push(text) },
    });
  });
  await openVertex(page);
  await expect(page.getByTestId("set-cmd-copied")).toHaveCount(0);
  await page.getByTestId("set-cmd-copy").click();
  await expect(page.getByTestId("set-cmd-copied")).toContainText("Copied");
  expect(await page.evaluate(() => (window as unknown as { __copied: string[] }).__copied)).toEqual([
    "gcloud auth application-default login",
  ]);
  // …and it goes back to the copy glyph by itself.
  await expect(page.getByTestId("set-cmd-copied")).toHaveCount(0, { timeout: 4_000 });
});

test("Test & save names an empty required field on the spot, then shows a backend failure beside the button", async ({
  page,
}) => {
  let verifyCalls = 0;
  await page.route("**/v1/providers/verify", (route) => {
    verifyCalls += 1;
    return route.fulfill({
      json: { ok: false, error: "Credentials work but lack Vertex AI access in this project." },
    });
  });
  await openVertex(page);
  // Location arrives prefilled (it used to be a grey placeholder that read as a value).
  await expect(page.getByTestId("set-field-location")).toHaveValue("global");

  await page.getByTestId("set-test").click();
  const error = page.getByTestId("set-verify-error");
  await expect(error).toHaveText("Fill these in first: GCP project ID");
  await expect(error).toHaveAttribute("role", "alert");
  await expect(page.getByTestId("set-field-project")).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByTestId("set-field-project")).toBeFocused();
  expect(verifyCalls).toBe(0);

  // Typing clears the mark; a complete form reaches the backend and its answer lands in
  // the same place.
  await page.getByTestId("set-field-project").fill("my-project");
  await expect(error).toHaveCount(0);
  await expect(page.getByTestId("set-field-project")).not.toHaveAttribute("aria-invalid", "true");
  await page.getByTestId("set-test").click();
  await expect(error).toHaveText("Credentials work but lack Vertex AI access in this project.");
  expect(verifyCalls).toBe(1);
});
