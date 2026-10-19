import { expect } from "@playwright/test";
import { test } from "./fixtures";

// An unsent draft survives a page reload (upstream f24b3fd4 / b90c02d5, adapted: this fork
// lifts the draft to App, which now also mirrors the TEXT per session into localStorage under
// coworker:composer-draft:v1:<sessionId>; attachments stay in memory). Boot resumes the last
// session by switching from a throwaway id to the resumed one, so the restore has to come
// through the composer's resetKey path, not only a mount — which is exactly what a reload does.

const KEY_PREFIX = "coworker:composer-draft:v1:";

const storedDrafts = (page: import("@playwright/test").Page) =>
  page.evaluate((prefix) => {
    const out: Record<string, string> = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)!;
      if (k.startsWith(prefix)) out[k] = localStorage.getItem(k)!;
    }
    return out;
  }, KEY_PREFIX);

test("unsent draft survives reload", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Draft the launch note").first().click();
  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("draft before reload");

  // The write is a passive effect; make sure it landed (and under the documented key) before
  // navigating away from the page.
  await expect.poll(async () => Object.values(await storedDrafts(page))).toEqual(["draft before reload"]);

  await page.reload();
  await page.getByText("Draft the launch note").first().click();
  await expect(box).toHaveValue("draft before reload");
});

test("sending clears the stored draft — a reload comes back empty", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Draft the launch note").first().click();
  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("hello agent");
  await expect.poll(async () => Object.values(await storedDrafts(page))).toEqual(["hello agent"]);

  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(/Echo: hello agent/)).toBeVisible();
  await expect(box).toHaveValue("");
  await expect.poll(async () => storedDrafts(page)).toEqual({});

  await page.reload();
  await page.getByText("Draft the launch note").first().click();
  await expect(box).toBeVisible();
  await expect(box).toHaveValue("");
});
