// F3/F4 (2026-09-28): automations get a real work folder (instead of always running in an
// empty private one) and a "发送到微信" section on every task's detail page, however it was
// created — set/revoke a WeChat recipient without going through 编辑.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

async function openAutomations(page) {
  await page.goto("/");
  await page.getByTestId("nav-automations").click();
  await expect(page.getByText("Recurring tasks OpenWorker runs on a schedule.")).toBeVisible();
}

async function openTaskDetail(page, title = "Daily AI News") {
  await openAutomations(page);
  await page.getByText(title).first().click();
  await expect(page.getByRole("button", { name: /Run now/ })).toBeVisible();
}

function weixinBase(connected: boolean) {
  return {
    name: "weixin", title: "微信", icon: "微", blurb: "个人微信收发消息。",
    auth: "qr", two_way: true, channels: false, available: true, brand_color: "#07c160",
    logo: "weixin", fields: [], instructions: [], connected,
    account: connected ? "cb076c30413a@im.bot" : null, enabled: connected,
    allowed_users: [], tools: [], managed: false, managed_profile: false,
  };
}

test("plain new-automation form: picking a folder sends it in the create payload", async ({ page }) => {
  await openAutomations(page);
  await page.getByRole("button", { name: "+ New automation" }).click();
  const form = page.locator(".tmpl-form");

  await form.getByPlaceholder("Title (e.g. Daily equipment check)").fill("Folder test");
  await form
    .getByPlaceholder(/What should it do each run/)
    .fill("Read the ledger and summarize it.");

  await form.getByTestId("task-folder-trigger").click();
  await form.getByTestId("task-folder-browse").click();
  await expect(form.getByTestId("task-folder-trigger")).toContainText("picked-folder");

  await form.getByRole("button", { name: "Create automation" }).click();

  // Lands on the new task's detail with the picked folder shown (not "Dedicated folder").
  await expect(page.getByRole("button", { name: /Run now/ })).toBeVisible();
  await expect(page.getByText("/tmp/picked-folder")).toBeVisible();
});

test("task detail: 'Dedicated folder' for a private automation; edit round-trips to a real path and back", async ({
  page,
}) => {
  await openTaskDetail(page);
  // task-1 ships workspace_private: true — the row must say so, never a raw path.
  await expect(page.getByText("Dedicated folder").first()).toBeVisible();

  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByTestId("task-folder-trigger")).toContainText("Dedicated folder");

  await page.getByTestId("task-folder-trigger").click();
  await page.getByTestId("task-folder-browse").click();
  await expect(page.getByTestId("task-folder-trigger")).toContainText("picked-folder");
  await page.getByRole("button", { name: "Save" }).click();

  // Saved: the display row now shows the real path.
  await expect(page.getByText(/Run now/)).toBeVisible();
  await expect(page.getByText("/tmp/picked-folder")).toBeVisible();
  await expect(page.getByText("Dedicated folder")).toHaveCount(0);

  // Editing again starts from that path; picking "Dedicated folder" goes back to private.
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByTestId("task-folder-trigger")).toContainText("picked-folder");
  await page.getByTestId("task-folder-trigger").click();
  await page.getByTestId("task-folder-private-option").click();
  await expect(page.getByTestId("task-folder-trigger")).toContainText("Dedicated folder");
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByText("Dedicated folder").first()).toBeVisible();
  await expect(page.getByText("/tmp/picked-folder")).toHaveCount(0);
});

test("发送到微信 (not connected): names the missing connector and 'Go connect' opens Connectors", async ({
  page,
}) => {
  await page.route("**/v1/connectors", (route) =>
    route.fulfill({ json: { connectors: [weixinBase(false)] } }),
  );
  await openTaskDetail(page);

  await expect(page.getByText('Connect WeChat under "Connectors" first.')).toBeVisible();
  await page.getByRole("button", { name: "Go connect" }).click();
  await expect(page.getByTestId("connector-weixin")).toBeVisible();
});

test("发送到微信 (connected): set a recipient mints the grant + appends the delivery sentence; Revoke removes both", async ({
  page,
}) => {
  await openTaskDetail(page);

  // task-1 has a Slack grant already but no WeChat one — "Set recipient" shows, and this
  // grant must never double up under "Allowed without asking" (F4's last requirement).
  await expect(page.getByTestId("task-grants")).toContainText("slack:T1/C1");
  await expect(page.getByTestId("task-grants")).not.toContainText("weixin:");

  await page.getByTestId("deliver-weixin-set").click();
  const editor = page.getByTestId("deliver-weixin-editor");
  await expect(editor).toBeVisible();
  await expect(editor.getByTestId("deliver-weixin-save")).toBeDisabled();

  await editor.locator("input").first().click();
  await page.getByTestId("channel-suggestions").getByText("示例联系人", { exact: true }).click();
  await expect(editor.getByTestId("deliver-weixin-save")).toBeDisabled(); // consent still unticked
  await editor.getByTestId("deliver-weixin-consent").check();
  await expect(editor.getByTestId("deliver-weixin-save")).toBeEnabled();
  await editor.getByTestId("deliver-weixin-save").click();

  // The grant is listed under 发送到微信 by name, and still absent from the generic
  // "Allowed without asking" list — it now belongs exclusively to this section.
  await expect(page.getByTestId("deliver-weixin-grants")).toContainText("示例联系人");
  await expect(page.getByTestId("task-grants")).not.toContainText("weixin:");
  await expect(page.getByTestId("task-grants")).toContainText("slack:T1/C1");

  // The appended sentence is now part of the instructions (F4's exact wording).
  await expect(
    page.getByText(/send_message to send a short result to weixin:o9cq@im.wechat over WeChat/),
  ).toBeVisible();

  // Revoke drops the grant AND strips the sentence it appended (the two ride one PATCH).
  await page.getByTestId("deliver-weixin-grants").getByRole("button", { name: "Revoke" }).click();
  await expect(page.getByTestId("deliver-weixin-grants")).toHaveCount(0);
  await expect(page.getByTestId("deliver-weixin-set")).toBeVisible();
  await expect(
    page.getByText(/send_message to send a short result to weixin:o9cq@im.wechat over WeChat/),
  ).toHaveCount(0);
  // The original instructions text is untouched otherwise.
  await expect(page.getByText(/Fetch the latest AI news/)).toBeVisible();
});

test("发送到微信: revoking a template-embedded recipient drops the grant but leaves the wording alone", async ({
  page,
}) => {
  // The inspection template weaves "{{channel}}" into the middle of its own sentence
  // (tmpl_inspection_instructions), never as the F4-appended sentence — so Revoke here
  // must NOT touch the instructions text at all.
  await openAutomations(page);
  await page.getByRole("button", { name: "+ New automation" }).click();
  await page.getByTestId("qs-template-inspection").click();
  const cfg = page.getByTestId("qs-configure");

  const chan = page.locator('[data-testid="ob-channel"] input');
  await chan.click();
  await page.getByTestId("channel-suggestions").getByText("示例联系人", { exact: true }).click();
  await cfg.getByTestId("task-folder-trigger").click();
  await cfg.getByTestId("task-folder-browse").click();
  await expect(page.getByTestId("ob-create")).toBeEnabled();
  await page.getByTestId("ob-create").click();
  await expect(page.getByRole("button", { name: /Run now/ })).toBeVisible();

  const instructionsBefore = await page.locator(".sched-instructions").textContent();
  expect(instructionsBefore).toMatch(/weixin:o9cq@im\.wechat/);

  await page.getByTestId("deliver-weixin-grants").getByRole("button", { name: "Revoke" }).click();
  await expect(page.getByTestId("deliver-weixin-grants")).toHaveCount(0);

  // The recipe's own sentence (with the address baked in) survives verbatim.
  const instructionsAfter = await page.locator(".sched-instructions").textContent();
  expect(instructionsAfter).toBe(instructionsBefore);
});
