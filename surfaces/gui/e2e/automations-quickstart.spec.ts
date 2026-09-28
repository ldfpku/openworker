// The Automations quickstart (UX-DECISIONS §29): ONE template system — role templates,
// connect rows, and the §25 consent line in the page's "Start from a template" grid. The
// lineup is the manufacturing set (2026-09-01, the session-intro cards' shift continued):
// two WeChat-delivered recipes gated on the weixin connector — whose connect is the LOCAL
// QR modal, never the cloud broker — plus folder-driven templates with no connections.
// Cards carry §27's connector-dot vocabulary; picking one expands the configure card.
//
// F2 (2026-09-28): every template except "news" now also requires a work folder pick before
// create — the config card carries a TaskFolderField and the create button's gate hint names
// it. Two TaskFolderField instances can be on the page at once (the plain "+ New automation"
// form AND the picked template's configure card both render while the form is open), so every
// folder query below is scoped to its own container (`cfg` for the quickstart card).
import { expect } from "@playwright/test";
import { test } from "./fixtures";

async function openAutomations(page) {
  await page.goto("/");
  await page.getByTestId("nav-automations").click();
  await expect(page.getByText("Recurring tasks OpenWorker runs on a schedule.")).toBeVisible();
}

// The fixtures seed one task, so the quickstart isn't on the bare list — surface it via the
// "+ New automation" toggle (empty state shows it without the toggle; covered indirectly by
// the delete test in automations-manage.spec.ts).
async function openQuickstart(page) {
  await openAutomations(page);
  await page.getByRole("button", { name: "+ New automation" }).click();
  await expect(page.getByText("Start from a template")).toBeVisible();
}

// Picks the folder via the "Choose a folder…" browse item — the shared fixture's
// /v1/workspaces/pick always returns /tmp/picked-folder, regardless of which field asked.
async function browseFolder(cfg) {
  await cfg.getByTestId("task-folder-trigger").click();
  await cfg.getByTestId("task-folder-browse").click();
}

// The shared fixture serves weixin already-connected (its detail-page specs want that), so
// the gating flow overrides the connectors payload per test — the google-paused.spec.ts
// pattern — with a mutable flag the mocked QR login flips.
function weixinBase(connected: boolean) {
  return {
    name: "weixin", title: "微信", icon: "微", blurb: "个人微信收发消息。",
    auth: "qr", two_way: true, channels: false, available: true, brand_color: "#07c160",
    logo: "weixin", fields: [], instructions: [], connected,
    account: connected ? "cb076c30413a@im.bot" : null, enabled: connected,
    allowed_users: [], tools: [], managed: false, managed_profile: false,
  };
}

test("weixin recipe: gated on connect, then recipient, then folder; consent mints the grant", async ({
  page,
}) => {
  const wx = { connected: false };
  await page.route("**/v1/connectors", (route) =>
    route.fulfill({ json: { connectors: [weixinBase(wx.connected)] } }),
  );
  // The QR login is fully local: POST starts it, the pane's 1s status poll lands
  // "confirmed", and onConnected closes the modal — no cloud sign-in anywhere.
  await page.route("**/v1/connectors/weixin/qr-login", (route) => {
    wx.connected = true;
    return route.fulfill({ json: { ok: true, started: true } });
  });
  await page.route("**/v1/connectors/weixin/qr-status", (route) =>
    route.fulfill({ json: wx.connected ? { state: "confirmed" } : { state: "starting" } }),
  );
  // A weixin DM contact in the picker's recent list (the shared fixture only has Slack).
  await page.route("**/v1/channels/recent", (route) =>
    route.fulfill({
      json: {
        channels: [
          { channel: "weixin:o9cq@im.wechat", name: "生产调度", last_from: "生产调度", last_text: "收到" },
        ],
      },
    }),
  );

  await openQuickstart(page);

  // Daily inspection reminder: weixin not connected yet — no recipe form, and the gate
  // names the missing piece. §30: the card names its template.
  await page.getByTestId("qs-template-inspection").click();
  const cfg = page.getByTestId("qs-configure");
  await expect(cfg).toContainText("Set up");
  await expect(cfg).toContainText("Daily inspection reminder");
  await expect(page.getByTestId("ob-recipe")).toHaveCount(0);
  await expect(page.getByTestId("ob-create")).toBeDisabled();
  await expect(page.getByTestId("ob-create-hint")).toContainText("Connect 微信");

  // Connect opens the standard QR modal (weixin is auth:"qr") — the cloud pane never
  // appears. The mocked login confirms on the first poll; the modal closes itself and
  // the row flips ✓ on the refresh.
  await page.getByTestId("ob-connect-weixin").click();
  await expect(page.getByTestId("add-connection-modal")).toBeVisible();
  await expect(page.getByTestId("ob-cloudpane")).toHaveCount(0);
  await expect(page.getByTestId("add-connection-modal")).toHaveCount(0, { timeout: 15_000 });
  await expect(cfg.getByText("✓ Connected")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ob-recipe")).toBeVisible();

  // Connected but no recipient → the gate names the missing piece (tester catch 2026-07-12).
  await expect(page.getByTestId("ob-create-hint")).toContainText("Pick a recipient");

  // Recipient picked BY NAME (the stored value stays the raw weixin:… address, shown WITHOUT
  // a "#" — F5: only Slack targets get that prefix); §25 consent pre-checked.
  const chan = page.locator('[data-testid="ob-channel"] input');
  await chan.click();
  await page.getByTestId("channel-suggestions").getByText("生产调度", { exact: true }).click();
  await expect(chan).toHaveValue("生产调度");
  await expect(page.getByTestId("ob-consent")).toBeChecked();

  // Recipient picked but no folder yet (F2) → the gate now names THAT missing piece.
  await expect(page.getByTestId("ob-create")).toBeDisabled();
  await expect(page.getByTestId("ob-create-hint")).toContainText(
    "Choose the folder your records live in before creating.",
  );

  // Pick the work folder and create lands on the task's detail with the standing grant listed.
  await browseFolder(cfg);
  await expect(cfg.getByTestId("task-folder-trigger")).toContainText("picked-folder");
  await expect(page.getByTestId("ob-create")).toBeEnabled();
  await page.getByTestId("ob-create").click();

  await expect(page.getByRole("button", { name: /Run now/ })).toBeVisible();
  await expect(page.getByText("Daily inspection reminder").first()).toBeVisible();
  // The grant is send_message → weixin:… — F4 gives those their own "发送到微信" section
  // (by recipient name) rather than listing them under "Allowed without asking".
  await expect(page.getByTestId("deliver-weixin-grants")).toContainText("生产调度");
  await expect(page.getByTestId("task-grants")).toHaveCount(0);
});

test("QR connect never hits the cloud gate: modal opens signed-out, Escape restores the row", async ({
  page,
}) => {
  // weixin stays disconnected: the QR session starts but is never confirmed.
  await page.route("**/v1/connectors", (route) =>
    route.fulfill({ json: { connectors: [weixinBase(false)] } }),
  );
  await page.route("**/v1/connectors/weixin/qr-login", (route) =>
    route.fulfill({ json: { ok: true, started: true } }),
  );
  await page.route("**/v1/connectors/weixin/qr-status", (route) =>
    route.fulfill({ json: { state: "waiting" } }),
  );

  await openQuickstart(page);
  await page.getByTestId("qs-template-quality").click();

  // Signed OUT of cloud (the fixture default) — the click must open the LOCAL QR modal,
  // not the one-sign-in pane, and must not start the broker's waiting narration.
  await page.getByTestId("ob-connect-weixin").click();
  await expect(page.getByTestId("add-connection-modal")).toBeVisible();
  await expect(page.getByTestId("ob-cloudpane")).toHaveCount(0);
  await expect(page.getByTestId("ob-connect-wait")).toHaveCount(0);

  // Escape closes the modal (its own affordance); the Connect button is simply back.
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("add-connection-modal")).toHaveCount(0);
  await expect(page.getByTestId("ob-connect-weixin")).toBeVisible();
});

test("delivery recipe, in-app delivery: no consent line, folder still required", async ({ page }) => {
  await openQuickstart(page);
  await page.getByTestId("qs-template-delivery").click();
  const cfg = page.getByTestId("qs-configure");

  // No connect rows, no consent checkbox — in-app delivery needs neither — but the recipe
  // form shows straight away with the deliver-to choice AND the work-folder picker (F2).
  await expect(page.getByTestId("ob-recipe")).toBeVisible();
  await expect(page.getByTestId("ob-consent")).toHaveCount(0);
  const deliver = page.getByRole("button", { name: "Deliver to" });
  await expect(deliver).toContainText("In the app");

  await expect(page.getByTestId("ob-create")).toBeDisabled();
  await expect(page.getByTestId("ob-create-hint")).toContainText(
    "Choose the folder your records live in before creating.",
  );

  await browseFolder(cfg);
  await expect(page.getByTestId("ob-create")).toBeEnabled();
  await page.getByTestId("ob-create").click();
  await expect(page.getByRole("button", { name: /Run now/ })).toBeVisible();
  await expect(page.getByText("Delivery-risk check").first()).toBeVisible();
});

test("delivery recipe, WeChat DM: picking it turns on the recipient picker, consent, and the send_message grant", async ({
  page,
}) => {
  // The shared fixture's weixin connector is already connected, so switching to WeChat DM
  // goes straight to the recipient/consent gate — no connect row appears.
  await openQuickstart(page);
  await page.getByTestId("qs-template-delivery").click();
  const cfg = page.getByTestId("qs-configure");

  const deliver = page.getByRole("button", { name: "Deliver to" });
  await deliver.click();
  await page.getByRole("option", { name: /WeChat DM/ }).click();
  await expect(deliver).toContainText("WeChat DM");

  // The consent line and recipient picker now appear, same as inspection/quality.
  await expect(page.getByTestId("ob-consent")).toBeVisible();
  await expect(page.getByTestId("ob-channel")).toBeVisible();
  await expect(page.getByTestId("ob-create")).toBeDisabled();
  await expect(page.getByTestId("ob-create-hint")).toContainText("Pick a recipient");

  // The shared fixture's channels/recent carries one WeChat contact (no Slack "#").
  const chan = page.locator('[data-testid="ob-channel"] input');
  await chan.click();
  await page.getByTestId("channel-suggestions").getByText("示例联系人", { exact: true }).click();
  await expect(chan).toHaveValue("示例联系人");
  await expect(page.getByTestId("ob-consent")).toBeChecked();

  // Recipient set, folder still missing.
  await expect(page.getByTestId("ob-create")).toBeDisabled();
  await expect(page.getByTestId("ob-create-hint")).toContainText(
    "Choose the folder your records live in before creating.",
  );
  await browseFolder(cfg);
  await expect(page.getByTestId("ob-create")).toBeEnabled();

  await page.getByTestId("ob-create").click();
  await expect(page.getByRole("button", { name: /Run now/ })).toBeVisible();
  await expect(page.getByText("Delivery-risk check").first()).toBeVisible();
  // The grant rides through exactly like inspection/quality's — filed under "发送到微信"
  // by recipient name (F4), not "Allowed without asking" — and the instructions carry the
  // chosen WeChat address (the same {{channel}} substitution the other recipes use).
  await expect(page.getByTestId("deliver-weixin-grants")).toContainText("示例联系人");
  await expect(
    page.getByText(/Send it to weixin:o9cq@im\.wechat over WeChat using send_message/),
  ).toBeVisible();
});

test("no-connection template: When is editable, no folder row, and create opens the detail", async ({
  page,
}) => {
  await openQuickstart(page);
  // The card says so on its face.
  await expect(page.getByTestId("qs-template-news")).toContainText("No connections needed");
  await page.getByTestId("qs-template-news").click();

  // No connect rows, no consent, no folder field (news reads the web, not a work folder) —
  // just When (day × time) and an enabled Create.
  const cfg = page.getByTestId("qs-configure");
  await expect(page.getByTestId("ob-consent")).toHaveCount(0);
  await expect(cfg.getByTestId("task-folder-field")).toHaveCount(0);
  await expect(
    page.getByTestId("ob-recipe").getByRole("button", { name: "Day" }),
  ).toContainText("Every day");
  await expect(page.getByTestId("ob-create")).toBeEnabled();
  await page.getByTestId("ob-create").click();

  await expect(page.getByRole("button", { name: /Run now/ })).toBeVisible();
  await expect(page.getByText("Industry news briefing").first()).toBeVisible();
});
