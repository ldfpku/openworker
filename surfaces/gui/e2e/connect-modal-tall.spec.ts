// The add-connection modal must never render taller than the window. Email (IMAP) is the
// tallest pane the app ships — 4 numbered instructions + 7 fields — and before the cap it
// measured 850px, so on a 1280x720 window it ran ~230px past the bottom with Connect
// unreachable and no page scroll to recover it (the overlay is fixed inset-0).
//
// The shared fixture serves no email connector, so this spec overrides the connectors
// payload per test, like google-paused.spec.ts does. Fields and instructions are copied
// from the real descriptor (coworker/connectors/descriptors.py, name="email").
import { expect } from "@playwright/test";
import { test } from "./fixtures";

const f = (key: string, label: string, extra: Record<string, unknown> = {}) => ({
  key, label, secret: false, required: true, help: "", placeholder: "", ...extra,
});

const EMAIL = {
  name: "email",
  title: "Email (IMAP)",
  icon: "✉",
  blurb: "Read, search, and send mail from any IMAP account — Gmail, iCloud, Fastmail, or custom.",
  auth: "app_password",
  two_way: false,
  channels: false,
  available: true,
  brand_color: "#666666",
  logo: "email",
  fields: [
    f("address", "Email address", { placeholder: "you@gmail.com" }),
    f("app_password", "App password", { secret: true, help: "Gmail/iCloud: generate an app password (requires 2-step verification). Not your account password." }),
    f("display_name", "Display name", { required: false, help: "Shown as the From name on sent mail." }),
    f("imap_host", "IMAP host (advanced)", { required: false, help: "Only needed for providers we don't auto-detect.", placeholder: "imap.example.com" }),
    f("imap_port", "IMAP port (advanced)", { required: false, placeholder: "993" }),
    f("smtp_host", "SMTP host (advanced)", { required: false, placeholder: "smtp.example.com" }),
    f("smtp_port", "SMTP port (advanced)", { required: false, placeholder: "587" }),
  ],
  instructions: [
    "Gmail: turn on 2-Step Verification, then create an app password at myaccount.google.com/apppasswords.",
    "iCloud: generate an app-specific password at account.apple.com → Sign-In and Security.",
    "Enter your address and the app password below. Gmail, iCloud, and Fastmail servers are detected automatically; for other providers fill in the IMAP/SMTP hosts.",
    "Note: Google Workspace and Microsoft 365 accounts often have IMAP or app passwords disabled by the org admin.",
  ],
  connected: false,
  account: null,
  enabled: false,
  allowed_users: [],
  tools: [],
  managed: false,
  managed_profile: false,
};

async function openEmailModal(page, connectors = [EMAIL]) {
  await page.route("**/v1/connectors", (route) => route.fulfill({ json: { connectors } }));
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Connectors", exact: true }).click();
  await page.getByTestId("connector-email").getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByTestId("add-connection-modal")).toBeVisible();
}

test("the tallest connect modal stays inside the window", async ({ page }) => {
  await openEmailModal(page);

  const panel = page.getByTestId("add-connection-modal").getByRole("dialog");
  const box = (await panel.boundingBox())!;
  const viewport = page.viewportSize()!;
  // Behavioural, not a change-detector on the 80vh constant: the panel must end above the fold.
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
  expect(box.y).toBeGreaterThanOrEqual(0);
});

test("Connect is reachable — the body scrolls, the header does not", async ({ page }) => {
  await openEmailModal(page);

  const body = page.getByTestId("modal-body");
  // The content really is taller than the box, i.e. this test would catch a regression.
  const overflows = await body.evaluate((el) => el.scrollHeight > el.clientHeight + 1);
  expect(overflows).toBe(true);

  await body.evaluate((el) => el.scrollTo(0, el.scrollHeight));

  const connect = page.getByTestId("modal-body").getByRole("button", { name: "Connect", exact: true });
  await expect(connect).toBeInViewport();
  // The pinned header survives the scroll — that is the point of the flex-column split.
  await expect(page.getByText("Connect Email (IMAP)")).toBeInViewport();
  // And it is genuinely clickable, not just painted inside the viewport. The rejection
  // also exercises the companion fix: ConnectSetup renders its error BELOW the button, so
  // once the body scrolls the message would otherwise land past the visible edge and the
  // click would read as "nothing happened".
  await page.route("**/v1/connectors/email/connect", (route) =>
    route.fulfill({ json: { ok: false, error: "That app password was rejected." } }),
  );
  await connect.click();
  await expect(page.getByText("That app password was rejected.")).toBeInViewport();
});

test("a short modal still hugs its content — no stretched box, no scrollbar", async ({ page }) => {
  const short = { ...EMAIL, fields: [EMAIL.fields[0]], instructions: [] };
  await openEmailModal(page, [short]);

  const box = (await page.getByTestId("add-connection-modal").getByRole("dialog").boundingBox())!;
  const viewport = page.viewportSize()!;
  // max-h, never h: one field must not inflate to the cap.
  expect(box.height).toBeLessThan(viewport.height * 0.5);
  const scrolls = await page.getByTestId("modal-body").evaluate((el) => el.scrollHeight > el.clientHeight + 1);
  expect(scrolls).toBe(false);
});
