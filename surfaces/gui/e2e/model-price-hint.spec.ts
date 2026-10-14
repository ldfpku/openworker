import type { Locator, Page, Route } from "@playwright/test";
import { test, expect } from "./fixtures";

// Owner ask 2026-10-14: show a price hint next to the models (what a model costs and,
// roughly, how capable it is). Only the company AI Gateway has authoritative prices — its
// guard's /gate/models lists USD per 1M input / output tokens, and marks models the
// administrator opened to 总经理 / 管理员 only as tier "limited". /v1/settings passes both
// on as `model_prices` / `model_tiers`; the three model lists (Settings ▸ Models' "In the
// composer's picker" card, the gateway's own checklist, the composer's picker) show the
// hint and a "Restricted" tag for exactly what is there and nothing for anything else.
//
// Runs in Chromium AND WebKit: the hint shares a flex row with the provider tag and the
// default badge, and the Mac app is WebKit.
const SOL = "aigw:openai/gpt-6.1-sol";
const FLASH = "aigw:google-ai-studio/gemini-3.7-flash";
const LUNA = "aigw:openai/gpt-6-luna";
const OPUS = "anthropic:claude-opus-4-8";

const SETTINGS = {
  provider: "openai",
  model: OPUS,
  models: [OPUS, "gpt-5.5", SOL, FLASH, LUNA],
  model_labels: {
    [OPUS]: "Claude Opus 4.8 · Anthropic",
    [SOL]: "GPT-6.1 Sol · via Cloudflare",
    [FLASH]: "Gemini 3.7 Flash · via Cloudflare",
    [LUNA]: "GPT-6 Luna · via Cloudflare",
  },
  // Sol: priced and restricted. Flash: sub-dollar prices. Luna: on the list, but the guard
  // gave no price — it must look like any other row. The two direct-provider models are
  // not in either map at all.
  model_prices: { [SOL]: { in: 3, out: 15 }, [FLASH]: { in: 0.15, out: 0.6 } },
  model_tiers: { [SOL]: "limited" },
  has_key: true,
  model_ready: true,
  source: "store",
  onboarded: true,
  surfaces: { cowork: true, chat: false, code: true },
  nav_layout: "flat",
  scratch_base: "~/OpenWorker",
  secrets_path: "/Users/test/.config/coworker/secrets.json",
};

const LIVE = { supported: true, live: true, fetched_at: "2026-10-14T01:00:00Z", error: null, count: 3 };
const PROVIDERS = [
  { name: "openai", title: "OpenAI", needs_key: true, fields: [{ key: "api_key", label: "OpenAI API key", secret: true, required: true, help: "", placeholder: "sk-…" }], configured: true, values: {}, suggested_models: ["gpt-5.5"], recommended_model: null, catalog: { ...LIVE, count: 1 } },
  { name: "anthropic", title: "Claude (Anthropic)", needs_key: true, fields: [{ key: "api_key", label: "API key", secret: true, required: true, help: "", placeholder: "sk-…" }], configured: true, values: {}, suggested_models: ["claude-opus-4-8"], recommended_model: null, catalog: { ...LIVE, count: 1 } },
  {
    name: "aigw",
    title: "Cloudflare AI Gateway",
    needs_key: true,
    blurb: "Sign in with your work email — no API key of your own.",
    fields: [],
    configured: true,
    values: {},
    suggested_models: ["openai/gpt-6.1-sol", "google-ai-studio/gemini-3.7-flash", "openai/gpt-6-luna"],
    recommended_model: "anthropic/claude-sonnet-5",
    catalog: LIVE,
  },
];

async function mockGateway(page: Page) {
  const get = (body: unknown) => (route: Route) =>
    route.request().method() === "GET" ? route.fulfill({ json: body }) : route.fallback();
  await page.route("**/v1/settings", get(SETTINGS));
  await page.route("**/v1/providers", get(PROVIDERS));
  await page.route(
    "**/v1/aigw/status",
    get({ signed_in: true, pending: false, expires_at: 0, registered: true, pasted_session: false }),
  );
}

async function openModels(page: Page) {
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Models", exact: true }).click();
}

const priceOf = (scope: Locator, id: string) => scope.getByTestId(`mlist-price-${id}`);
const tagOf = (scope: Locator, id: string) => scope.getByTestId(`mlist-restricted-${id}`);

test("Settings ▸ Models: gateway rows show the price hint and the Restricted tag", async ({ page }) => {
  await mockGateway(page);
  await openModels(page);

  // -- the "In the composer's picker" card ---------------------------------------------
  const card = page.getByTestId("composer-picker");
  await expect(priceOf(card, SOL)).toHaveText("$3 / $15 per 1M tokens");
  await expect(priceOf(card, SOL)).toHaveAttribute("title", "Input $3 · output $15 (USD per 1M tokens)");
  await expect(priceOf(card, FLASH)).toHaveText("$0.15 / $0.6 per 1M tokens");
  await expect(tagOf(card, SOL)).toHaveText("Restricted");
  await expect(tagOf(card, SOL)).toHaveAttribute("title", "Open to the General Manager and administrators only");
  // An unpriced gateway model and the direct-provider models: nothing extra.
  await expect(card.getByTestId(/^mlist-price-/)).toHaveCount(2);
  await expect(card.getByTestId(/^mlist-restricted-/)).toHaveCount(1);
  const lunaRow = card.locator(".mlist-row").filter({ hasText: "GPT-6 Luna" });
  await expect(lunaRow).toHaveText(/^GPT-6 Luna · via CloudflareCloudflare AI GatewayMake default$/);
  // The provider tag is still there, after the name cell.
  const solRow = card.locator(".mlist-row").filter({ hasText: "GPT-6.1 Sol" });
  await expect(solRow).toContainText("Cloudflare AI Gateway");

  // -- layout ------------------------------------------------------------------------------
  // The hint lives in the row's flexible name cell. With room it sits on the name's line;
  // in a narrower window (this card's rows also carry a provider tag and a button) the
  // tag + price drop UNDER the name, aligned with it, and the name keeps its full text.
  // Either way the provider tag stays exactly where it is on a row without a hint.
  const boxes = async () => {
    const box = async (l: Locator) => (await l.boundingBox())!;
    const name = solRow.locator(".mlist-name");
    return {
      row: await box(solRow),
      plain: await box(lunaRow),
      name: await box(name),
      tag: await box(tagOf(card, SOL)),
      price: await box(priceOf(card, SOL)),
      provider: await box(solRow.getByText("Cloudflare AI Gateway", { exact: true })),
      plainProvider: await box(lunaRow.getByText("Cloudflare AI Gateway", { exact: true })),
      // Is the name ellipsized? Its text's natural width against the box it got (measured
      // with a Range: scrollWidth/clientWidth round fractional widths differently in WebKit).
      nameCut: await name.evaluate((el) => {
        const range = document.createRange();
        range.selectNodeContents(el);
        return range.getBoundingClientRect().width > el.getBoundingClientRect().width + 1;
      }),
    };
  };
  const midY = (b: { y: number; height: number }) => b.y + b.height / 2;
  // Resize, then wait until the row has stopped moving before measuring it: the page
  // around it re-lays-out over a few frames, and a box read mid-way is not the layout.
  const resizeTo = async (width: number) => {
    await page.setViewportSize({ width, height: 800 });
    let last = "";
    await expect
      .poll(
        async () => {
          const now = JSON.stringify(await solRow.boundingBox());
          const same = now === last;
          last = now;
          return same;
        },
        { intervals: [150] },
      )
      .toBe(true);
    return boxes();
  };

  const wide = await resizeTo(1600);
  // One line: same height as a row without a hint; name, tag, price left to right.
  expect(Math.abs(wide.row.height - wide.plain.height)).toBeLessThanOrEqual(1);
  expect(Math.abs(midY(wide.price) - midY(wide.name))).toBeLessThanOrEqual(2);
  expect(wide.tag.x).toBeGreaterThanOrEqual(wide.name.x + wide.name.width);
  expect(wide.price.x).toBeGreaterThanOrEqual(wide.tag.x + wide.tag.width);
  expect(wide.price.x + wide.price.width).toBeLessThanOrEqual(wide.provider.x);
  expect(wide.nameCut).toBe(false);
  expect(Math.abs(wide.provider.x - wide.plainProvider.x)).toBeLessThanOrEqual(1);

  // Narrow the window until the hint no longer fits beside the name. The exact width
  // depends on text metrics that differ a little per engine and platform, so it is found,
  // not assumed; the steps are small enough that the name itself still fits.
  const wrapped = (b: Awaited<ReturnType<typeof boxes>>) => b.tag.y >= b.name.y + b.name.height - 1;
  let narrow = wide;
  for (let width = 1500; width >= 900 && !wrapped(narrow); width -= 50) narrow = await resizeTo(width);
  expect(wrapped(narrow), "the hint drops under the name before the row gets tight").toBe(true);
  // Two tidy lines: the name whole on the first, tag + price under it from the name's left
  // edge, the price itself on a single line.
  expect(narrow.nameCut).toBe(false);
  expect(narrow.tag.y).toBeGreaterThanOrEqual(narrow.name.y + narrow.name.height - 1);
  expect(Math.abs(narrow.tag.x - narrow.name.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(midY(narrow.price) - midY(narrow.tag))).toBeLessThanOrEqual(2);
  expect(narrow.price.x).toBeGreaterThanOrEqual(narrow.tag.x + narrow.tag.width);
  expect(narrow.price.height).toBeLessThan(22);
  // Nothing runs into the provider tag, the tag has not moved, nothing leaves the row.
  expect(narrow.price.x + narrow.price.width).toBeLessThanOrEqual(narrow.provider.x);
  expect(narrow.name.x + narrow.name.width).toBeLessThanOrEqual(narrow.provider.x);
  expect(Math.abs(narrow.provider.x - narrow.plainProvider.x)).toBeLessThanOrEqual(1);
  expect(narrow.provider.x + narrow.provider.width).toBeLessThanOrEqual(narrow.row.x + narrow.row.width);
  expect(narrow.price.y + narrow.price.height).toBeLessThanOrEqual(narrow.row.y + narrow.row.height + 0.5);
  await page.setViewportSize({ width: 1280, height: 800 });

  // -- the gateway's own checklist -------------------------------------------------------
  await page.getByTestId("set-provider-aigw").click();
  const list = page.locator(".mlist");
  await expect(priceOf(list, SOL)).toHaveText("$3 / $15 per 1M tokens");
  await expect(priceOf(list, FLASH)).toHaveText("$0.15 / $0.6 per 1M tokens");
  await expect(tagOf(list, SOL)).toHaveText("Restricted");
  await expect(list.getByTestId(/^mlist-price-/)).toHaveCount(2);
  await expect(list.getByTestId(/^mlist-restricted-/)).toHaveCount(1);
  await expect(list.locator(".mlist-row").filter({ hasText: "GPT-6 Luna" })).toHaveText(
    /^GPT-6 Luna · via CloudflareMake default$/,
  );

  // Another provider's checklist is untouched.
  await page.getByTestId("set-back").click();
  await page.getByTestId("set-provider-openai").click();
  await expect(page.locator(".mlist .mlist-row")).toHaveCount(1);
  await expect(page.locator(".mlist").getByTestId(/^mlist-(price|restricted)-/)).toHaveCount(0);
});

test("composer picker: gateway models show the compact price and the Restricted tag", async ({ page }) => {
  await mockGateway(page);
  await page.goto("/");
  const picker = page.locator(".dd").filter({ hasText: "Claude Opus 4.8" });
  await picker.locator(".pill").click();
  const menu = page.locator(".dd-menu");
  await expect(menu).toBeVisible();

  const sol = menu.locator(".dd-item").filter({ hasText: "GPT-6.1 Sol" });
  await expect(sol.locator(".dd-meta")).toHaveText("$3 / $15");
  await expect(sol.locator(".dd-meta")).toHaveAttribute("title", "Input $3 · output $15 (USD per 1M tokens)");
  await expect(sol.locator(".dd-tag")).toHaveText("Restricted");
  await expect(sol.locator(".dd-tag")).toHaveAttribute("title", "Open to the General Manager and administrators only");
  await expect(menu.locator(".dd-item").filter({ hasText: "Gemini 3.7 Flash" }).locator(".dd-meta")).toHaveText(
    "$0.15 / $0.6",
  );
  // Only what the guard priced / restricted carries anything.
  await expect(menu.locator(".dd-meta")).toHaveCount(2);
  await expect(menu.locator(".dd-tag")).toHaveCount(1);
  await expect(menu.locator(".dd-item").filter({ hasText: "GPT-6 Luna" })).toHaveText("GPT-6 Luna · via Cloudflare");

  // Compact: every row is one line, and the two prices end at the same x.
  const heights = await menu.locator(".dd-item").evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height));
  expect(Math.max(...heights) - Math.min(...heights)).toBeLessThanOrEqual(1);
  const rights = await menu
    .locator(".dd-meta")
    .evaluateAll((els) => els.map((el) => el.getBoundingClientRect().right));
  expect(Math.abs(rights[0] - rights[1])).toBeLessThanOrEqual(1);
  // The menu stays on screen.
  const box = await menu.boundingBox();
  const viewport = page.viewportSize()!;
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);

  // Picking a priced row still works (the click lands on the price note).
  await sol.locator(".dd-meta").click();
  await expect(page.locator(".dd").filter({ hasText: "GPT-6.1 Sol" })).toBeVisible();
});

test.describe("in Chinese", () => {
  test.use({ locale: "zh-CN" });

  test("the picker and the checklist use the agreed wording", async ({ page }) => {
    await mockGateway(page);
    await page.goto("/");
    await page.locator(".dd").filter({ hasText: "Claude Opus 4.8" }).locator(".pill").click();
    const sol = page.locator(".dd-menu .dd-item").filter({ hasText: "GPT-6.1 Sol" });
    await expect(sol.locator(".dd-meta")).toHaveText("$3 / $15");
    await expect(sol.locator(".dd-meta")).toHaveAttribute("title", "输入 $3 · 输出 $15（美元 / 百万 token）");
    await expect(sol.locator(".dd-tag")).toHaveText("限制使用");
    await expect(sol.locator(".dd-tag")).toHaveAttribute("title", "仅对总经理、管理员开放");
    await page.locator(".dd-backdrop").click();

    await page.getByTestId("account-row").click();
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await page.getByRole("button", { name: "模型", exact: true }).click();
    const card = page.getByTestId("composer-picker");
    await expect(priceOf(card, SOL)).toHaveText("$3 / $15 每百万 token");
    await expect(priceOf(card, SOL)).toHaveAttribute("title", "输入 $3 · 输出 $15（美元 / 百万 token）");
    await expect(tagOf(card, SOL)).toHaveText("限制使用");
    await expect(tagOf(card, SOL)).toHaveAttribute("title", "仅对总经理、管理员开放");
  });
});
