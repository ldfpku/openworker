// The DM-only connector page (WeChat): two_way with channels: false, so every inbound message
// is a DM and this page owns the whole delivery path. It used to own only half of it — you
// allow-listed a sender here and the session that would ANSWER them was picked on a different
// screen (Inbox ▸ Configure), with nothing here saying so. Owners allowed someone, got no
// reply, and had no way to find out why. These specs pin the two halves being on one page.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

async function openWeixinPage(page) {
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Connectors", exact: true }).click();
  await page.getByTestId("connector-weixin").click();
}

test("the page explains the flow end to end, reply included", async ({ page }) => {
  await openWeixinPage(page);

  await expect(page.getByText("How this works")).toBeVisible();
  await expect(page.getByText("the sender shows up under Recent senders")).toBeVisible();
  await expect(page.getByText("replays what they already said")).toBeVisible();
  // The step nobody could discover: something has to answer, and unset is not a dead end.
  await expect(page.getByText("replies straight back to 微信")).toBeVisible();
  // ...and where to look when a reply still doesn't arrive.
  await expect(page.getByText("Unrouted keeps every message that reached nobody")).toBeVisible();
});

test("the DM route lives on this page, defaulting to automatic", async ({ page }) => {
  await openWeixinPage(page);

  const route = page.getByTestId("dm-route-weixin");
  await expect(route).toContainText("Answers DMs");
  const select = route.locator("select");
  await expect(select).toHaveValue("");
  await expect(select.locator("option:checked")).toHaveText("Automatic — the first DM opens a session");

  // Picking a session persists — the page reads the same route Inbox ▸ Configure writes.
  await select.selectOption({ label: "Weekly plan 1" });
  await openWeixinPage(page);
  await expect(page.getByTestId("dm-route-weixin").locator("select")).toHaveValue("wp-1");
});

test("Allow & deliver takes the first-contact DM in one press", async ({ page }) => {
  await openWeixinPage(page);

  const parked = page.getByTestId("unauthorized-weixin");
  await expect(parked).toContainText("你当前使用的是哪种模型？");
  await page.getByTestId("parked-allow-deliver-wx-pk1").click();

  await expect(page.getByTestId("unauthorized-weixin")).toHaveCount(0);
  await expect(page.getByText("nobody yet")).toHaveCount(0);
  await expect(page.getByTestId("dm-route-weixin")).toBeVisible(); // route stays reachable after
});

test("channel subscriptions stay off a DM-only connector", async ({ page }) => {
  await openWeixinPage(page);
  await expect(page.getByTestId("listening-weixin")).toHaveCount(0);
});

test("a connected QR connector can re-scan without disconnecting", async ({ page }) => {
  // A WeChat login expires on Tencent's schedule and re-scanning is the fix, but the
  // only action a connected connector offered was Disconnect — which deletes the
  // profile and every approved sender with it. Routine expiry cost the whole allow-list.
  await openWeixinPage(page);

  // The allow-list this must not cost the user.
  await page.getByTestId("parked-allow-deliver-wx-pk1").click();
  await expect(page.getByTestId("unauthorized-weixin")).toHaveCount(0);

  await page.getByTestId("rescan-weixin").click();
  await expect(page.getByRole("button", { name: "Scan QR" })).toBeVisible();

  // Disconnect stays available, but is no longer the only way back in.
  await expect(page.getByRole("button", { name: "Disconnect" })).toBeVisible();
});
