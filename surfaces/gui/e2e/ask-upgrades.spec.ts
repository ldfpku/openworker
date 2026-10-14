import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures";

// OPE-51 — ask_user upgrades: rich options (descriptions, the Recommended tag, monospace
// previews with the two-pane layout) and grouped questions (the stepper). Seeded via a per-test
// inbox route override (later routes match first) so the base fixtures' counts — which
// inbox.spec.ts pins — stay untouched.

const BASE = {
  body: "",
  state: "pending",
  resolution: null as string | null,
  inbox: "default",
  created_at: "2026-07-29 08:00:00",
  resolved_at: null as string | null,
  session_title: "Investigate alerts",
  session_agent: "ops",
  session_workspace: "",
  session_exists: true,
};

const RICH_ITEM = {
  ...BASE,
  id: "inb-question-rich",
  session_id: "ops-1",
  kind: "question",
  title: "How should I format the report?",
  header: "Format",
  options: [
    {
      label: "Markdown table",
      description: "Compact and renders in the app",
      recommended: true,
      preview: "| env | status |\n| --- | --- |\n| staging | ok |",
    },
    {
      label: "Plain text",
      description: "Safest for email forwarding",
      preview: "env: staging\nstatus: ok",
    },
  ],
  allow_text: true,
  multi: false,
  questions: [],
};

const GROUPED_ITEM = {
  ...BASE,
  id: "inb-question-grouped",
  session_id: "ops-1",
  kind: "question",
  // The first question doubles as title/options (legacy-surface degradation, server parity).
  title: "Chart style?",
  header: "Chart style",
  options: ["Bar", "Line"],
  allow_text: false,
  multi: false,
  questions: [
    { question: "Chart style?", header: "Chart style", options: ["Bar", "Line"], allow_text: false, multi: false },
    { question: "Which distribution?", header: "Distribution", options: ["Stacked", "Grouped"], allow_text: true, multi: false },
  ],
};

/** Replace the Inbox's seeded items for this test (resolve mutates the local copy). */
async function seedInbox(page: Page, items: Record<string, unknown>[]) {
  const inbox = items.map((i) => ({ ...i }));
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.route(/\/v1\/inbox\/[^/]+\/resolve$/, (route) => {
    const path = new URL(route.request().url()).pathname;
    const id = decodeURIComponent(path.split("/").slice(-2)[0]);
    const it = inbox.find((x) => x.id === id);
    if (it) {
      it.state = "resolved";
      it.resolution = route.request().postDataJSON().resolution;
    }
    return route.fulfill(json({ ok: true }));
  });
  await page.route(/\/v1\/inbox(\?.*)?$/, (route) =>
    route.fulfill(json({ items: inbox.filter((i) => i.state === "pending") })),
  );
  return inbox;
}

async function openInbox(page: Page, expectTitle: string) {
  await page.goto("/");
  await page.getByTestId("inbox-chip").click();
  await expect(page.getByText(expectTitle)).toBeVisible();
}

test("rich options render descriptions + Recommended; the preview pane follows hover", async ({
  page,
}) => {
  await seedInbox(page, [RICH_ITEM]);
  await openInbox(page, "How should I format the report?");

  await expect(page.getByText("Compact and renders in the app")).toBeVisible();
  await expect(page.getByText("Recommended")).toBeVisible();

  // The pane opens on the first option holding a preview…
  const pane = page.getByTestId("question-preview");
  await expect(pane).toContainText("| env | status |");
  // …and follows hover to the other option.
  await page.getByRole("button", { name: /Plain text/ }).hover();
  await expect(pane).toContainText("env: staging");

  // Single-select still resolves on click, with the option's LABEL as the resolution.
  const resolved = page.waitForRequest(
    (r) => r.url().includes("/resolve") && r.method() === "POST",
  );
  await page.getByRole("button", { name: /Markdown table/ }).click();
  expect((await resolved).postDataJSON().resolution).toBe("Markdown table");
  await expect(page.getByText("How should I format the report?")).not.toBeVisible();
});

test("grouped questions step through the header chips and resolve as one answer map", async ({
  page,
}) => {
  await seedInbox(page, [GROUPED_ITEM]);
  await openInbox(page, "Chart style?");

  // Step 1: "Chart style · 1 of 2 · Distribution ›" — and no free-text row (allow_text: false).
  const stepper = page.getByTestId("question-stepper");
  await expect(stepper).toContainText("Chart style");
  await expect(stepper).toContainText("1 of 2");
  await expect(stepper).toContainText("Distribution ›");
  await expect(page.getByPlaceholder("Or type your own answer…")).not.toBeVisible();

  // Answering advances to step 2 (its free-text escape is back — allow_text: true).
  await page.getByRole("button", { name: "Bar", exact: true }).click();
  await expect(stepper).toContainText("2 of 2");
  await expect(page.getByText("Which distribution?")).toBeVisible();
  await expect(page.getByPlaceholder("Or type your own answer…")).toBeVisible();

  // ‹ steps back with the first answer re-askable; answer forward again.
  await page.getByRole("button", { name: "Previous question" }).click();
  await expect(stepper).toContainText("1 of 2");
  await page.getByRole("button", { name: "Bar", exact: true }).click();
  await expect(stepper).toContainText("2 of 2");

  // The final answer resolves the whole card with a JSON map keyed by header.
  const resolved = page.waitForRequest(
    (r) => r.url().includes("/resolve") && r.method() === "POST",
  );
  await page.getByRole("button", { name: "Stacked", exact: true }).click();
  expect((await resolved).postDataJSON().resolution).toBe(
    JSON.stringify({ "Chart style": "Bar", Distribution: "Stacked" }),
  );
  await expect(page.getByText("Nothing pending.")).toBeVisible();
});

// 开工前核对 (coworker/guidance.py): the engine's own pre-flight card wears its title and the
// skip button (server flag data.preflight), and a multi-select resolves as a JSON array so a
// label containing a comma survives the round trip.
const PREFLIGHT_ITEM = {
  ...BASE,
  id: "inb-question-preflight",
  session_id: "ops-1",
  kind: "question",
  title: "成果主要给谁看？",
  header: "给谁看",
  options: [{ label: "生产部长", recommended: true }],
  allow_text: true,
  multi: false,
  data: { preflight: true },
  questions: [
    { question: "成果主要给谁看？", header: "给谁看", options: [{ label: "生产部长", recommended: true }], allow_text: true, multi: false },
    { question: "依据哪些资料来做？", header: "依据在哪", options: ["检验记录, 机加", "不良品处理单"], allow_text: true, multi: true },
  ],
};

test("the pre-flight card shows its title, resolves multi-select as a JSON array, and can be skipped", async ({
  page,
}) => {
  await seedInbox(page, [PREFLIGHT_ITEM]);
  await openInbox(page, "成果主要给谁看？");
  await expect(page.getByTestId("preflight-title")).toHaveText("Pre-flight check");
  await expect(page.getByTestId("preflight-skip")).toBeVisible();

  await page.getByRole("button", { name: /生产部长/ }).click();
  await expect(page.getByText("依据哪些资料来做？")).toBeVisible();
  await page.getByRole("button", { name: "检验记录, 机加" }).click();
  await page.getByRole("button", { name: "不良品处理单" }).click();
  const resolved = page.waitForRequest((r) => r.url().includes("/resolve") && r.method() === "POST");
  await page.getByRole("button", { name: /Send \(2\)/ }).click();
  expect(JSON.parse((await resolved).postDataJSON().resolution)).toEqual({
    给谁看: "生产部长",
    依据在哪: ["检验记录, 机加", "不良品处理单"],
  });
});

test("the pre-flight skip button resolves with the skip sentinel", async ({ page }) => {
  await seedInbox(page, [PREFLIGHT_ITEM]);
  await openInbox(page, "成果主要给谁看？");
  const resolved = page.waitForRequest((r) => r.url().includes("/resolve") && r.method() === "POST");
  await page.getByTestId("preflight-skip").click();
  expect((await resolved).postDataJSON().resolution).toBe("__preflight_skip__");
  await expect(page.getByText("成果主要给谁看？")).not.toBeVisible();
});
