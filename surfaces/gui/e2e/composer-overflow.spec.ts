import { expect } from "@playwright/test";
import { test } from "./fixtures";

// The composer's single control row carries + attach · Mode · enhance · pre-flight · model ·
// send/stop. Everything but the model picker is flex:none, so when the session column gets
// narrow (artifact panel open, small window) the model label must give way — otherwise the
// row overflows the composer and Send/Stop sit outside its border, unreachable past the
// column edge (upstream #208, 4178d680). This fixture session keeps a ~330px side panel open,
// so at a 1100px viewport the session column leaves the row ~420px: the 205px model label has
// to give up ~65px (more with the wider Stop button). Pre-fix the row did not shrink at all
// and Send's right edge sat 18px past the composer's.
//
// Not narrower: below ~1000px the fixed controls alone (attach, Mode, enhance, pre-flight,
// Stop) exceed the row even with the picker at zero width, and WebKit renders "Stop" ~6px
// wider than Chromium — a degenerate column, not the truncation this pins.

const right = (b: { x: number; width: number }) => b.x + b.width;

test("narrow session column: Send, then Stop, stay inside the composer", async ({ page }) => {
  await page.setViewportSize({ width: 1_100, height: 800 });
  await page.goto("/");
  await page.getByText("Draft the launch note").first().click();

  const box = page.getByPlaceholder(/Ask the coworker/);
  await expect(box).toBeVisible();
  const composer = page.locator(".composer");

  // Idle: Send is the last control on the row.
  const [c1, send, model] = await Promise.all([
    composer.boundingBox(),
    page.getByRole("button", { name: "Send" }).boundingBox(),
    page.locator('[data-tour="model"]').boundingBox(),
  ]);
  expect(c1).not.toBeNull();
  expect(send).not.toBeNull();
  expect(right(send!)).toBeLessThanOrEqual(right(c1!));
  // The picker shrank rather than vanished: still a usable (truncated) chip, and it gave
  // way — the full label is ~205px.
  expect(model!.width).toBeGreaterThan(60);
  expect(model!.width).toBeLessThan(200);

  // Running: Stop replaces Send (a slow multi-second stream, see fixtures.ts).
  await box.fill("stream the epic");
  await box.press("Enter");
  const stopBtn = page.getByRole("button", { name: /Stop/ });
  await expect(stopBtn).toBeVisible();
  const [c2, stop] = await Promise.all([composer.boundingBox(), stopBtn.boundingBox()]);
  expect(c2).not.toBeNull();
  expect(stop).not.toBeNull();
  expect(right(stop!)).toBeLessThanOrEqual(right(c2!));
});
