// The model picker's badge slot. An Option carries exactly ONE badge, and two facts now
// compete for it: "free" (local Ollama) and "has a same-tier
// stand-in" (an AI Gateway model with a Dynamic Route, which survives a 429 on the shared
// wholesale pool by re-sending on its partner). Free wins the pill; the stand-in joins the
// tooltip. Getting that precedence wrong would either hide what a turn costs or promise a
// fallback on a model that has none.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Composer } from "./Composer";

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response),
  );
}

const MODELS = [
  "aigw:anthropic/claude-fable-5",
  "aigw:anthropic/claude-haiku-4-5",
  "ollama:qwen3-coder:30b",
];

const props = (extra: Partial<Parameters<typeof Composer>[0]> = {}) => ({
  mode: "interactive",
  model: "aigw:anthropic/claude-fable-5",
  models: MODELS,
  modelLabels: {
    "aigw:anthropic/claude-fable-5": "Claude Fable 5 · via Cloudflare",
    "aigw:anthropic/claude-haiku-4-5": "Claude Haiku 4.5 · via Cloudflare",
    "ollama:qwen3-coder:30b": "Qwen3 Coder · Ollama",
  },
  modelFallbacks: {
    "aigw:anthropic/claude-fable-5": "GPT-5.6 Sol · via Cloudflare",
    "ollama:qwen3-coder:30b": "GPT-5.6 Terra · via Cloudflare",
  },
  running: false,
  connected: true,
  modelReady: true,
  workspace: "code",
  sessionId: "s1",
  onSend: vi.fn(),
  onInterrupt: vi.fn(),
  onModeChange: vi.fn(),
  onModelChange: vi.fn(),
  ...extra,
});

/** The row of the (already open) picker whose label starts with `text`. */
function pickerRow(text: string): HTMLElement {
  const row = screen
    .getAllByText((_c, el) => el?.className === "dd-label")
    .find((el) => el.textContent?.includes(text));
  if (!row) throw new Error(`no picker row for ${text}`);
  return row as HTMLElement;
}

/** Open the picker and return the row whose label starts with `text`. */
function openRow(text: string): HTMLElement {
  fireEvent.click(screen.getByTitle(/Claude Fable 5/));
  return pickerRow(text);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Composer — the model picker's stand-in badge", () => {
  it("badges a routed gateway model and names its stand-in in the tooltip", () => {
    stubFetch();
    render(<Composer {...props()} />);
    const badge = openRow("Claude Fable 5").querySelector(".dd-badge");
    expect(badge?.textContent).toBe("Has stand-in");
    // The label's " · via Cloudflare" suffix is noise inside a sentence about a fallback.
    expect(badge?.getAttribute("title")).toContain("GPT-5.6 Sol");
    expect(badge?.getAttribute("title")).not.toContain("via Cloudflare");
  });

  it("leaves an unrouted model unbadged", () => {
    stubFetch();
    render(<Composer {...props()} />);
    expect(openRow("Claude Haiku 4.5").querySelector(".dd-badge")).toBeNull();
  });

  it("keeps Free in the single badge slot and folds the stand-in into its tooltip", () => {
    stubFetch();
    render(<Composer {...props()} />);
    const badge = openRow("Qwen3 Coder").querySelector(".dd-badge");
    expect(badge?.textContent).toBe("Free");
    expect(badge?.getAttribute("title")).toContain("no model bill");
    expect(badge?.getAttribute("title")).toContain("GPT-5.6 Terra");
  });

  it("badges nothing when the backend sends no fallback map (older server, or switch off)", () => {
    stubFetch();
    render(<Composer {...props({ modelFallbacks: undefined })} />);
    expect(openRow("Claude Fable 5").querySelector(".dd-badge")).toBeNull();
  });
});

// Company-gateway models show their list price at the row's right edge (numbers only — the
// tooltip has the unit) and a quiet "Restricted" tag when the administrator opened them to
// 总经理 / 管理员 only. Neither is a badge: the Free / stand-in pill keeps its one slot.
describe("Composer — the model picker's price note and Restricted tag", () => {
  const priced = (extra: Partial<Parameters<typeof Composer>[0]> = {}) =>
    props({
      modelPrices: {
        "aigw:anthropic/claude-fable-5": { in: 10, out: 50 },
        "aigw:anthropic/claude-haiku-4-5": { in: 1 },
      },
      modelTiers: { "aigw:anthropic/claude-fable-5": "limited" },
      ...extra,
    });

  it("shows the compact price with the spelled-out tooltip", () => {
    stubFetch();
    render(<Composer {...priced()} />);
    const meta = openRow("Claude Fable 5").querySelector(".dd-meta");
    expect(meta?.textContent).toBe("$10 / $50");
    expect(meta?.getAttribute("title")).toBe("Input $10 · output $50 (USD per 1M tokens)");
  });

  it("names the side when only one is priced", () => {
    stubFetch();
    render(<Composer {...priced()} />);
    expect(openRow("Claude Haiku 4.5").querySelector(".dd-meta")?.textContent).toBe("Input $1");
  });

  it("tags a limited model without taking the badge slot", () => {
    stubFetch();
    render(<Composer {...priced()} />);
    const row = openRow("Claude Fable 5");
    const tag = row.querySelector(".dd-tag");
    expect(tag?.textContent).toBe("Restricted");
    expect(tag?.getAttribute("title")).toBe("Open to the General Manager and administrators only");
    // The stand-in pill is still there, and still the only pill.
    expect(row.querySelector(".dd-badge")?.textContent).toBe("Has stand-in");
    expect(pickerRow("Claude Haiku 4.5").querySelector(".dd-tag")).toBeNull();
  });

  it("adds nothing to a model without data, or when the backend sends no maps", () => {
    stubFetch();
    const { unmount } = render(<Composer {...priced()} />);
    const local = openRow("Qwen3 Coder");
    expect(local.querySelector(".dd-meta")).toBeNull();
    expect(local.querySelector(".dd-tag")).toBeNull();
    unmount();
    render(<Composer {...props()} />);
    const row = openRow("Claude Fable 5");
    expect(row.querySelector(".dd-meta")).toBeNull();
    expect(row.querySelector(".dd-tag")).toBeNull();
    expect(row.querySelector(".chk-space")).toBeNull();
    expect(row.textContent).toBe("Claude Fable 5 · via CloudflareHas stand-in✓");
  });

  it("says it in Chinese with the agreed wording", async () => {
    stubFetch();
    const i18n = (await import("i18next")).default;
    await i18n.changeLanguage("zh");
    try {
      render(<Composer {...priced()} />);
      const row = openRow("Claude Fable 5");
      expect(row.querySelector(".dd-meta")?.textContent).toBe("$10 / $50");
      expect(row.querySelector(".dd-meta")?.getAttribute("title")).toBe(
        "输入 $10 · 输出 $50（美元 / 百万 token）",
      );
      expect(row.querySelector(".dd-tag")?.textContent).toBe("限制使用");
      expect(row.querySelector(".dd-tag")?.getAttribute("title")).toBe("仅对总经理、管理员开放");
    } finally {
      await i18n.changeLanguage("en");
    }
  });
});

// The default was a company-gateway model that has left this person's server list. The
// server substitutes nothing (owner call 2026-10-13): it reports model_ready=false with
// model_notice="default_model_gone", and the composer reuses its "No model" chip — the
// dead id is not offered, the reason is on screen, and a send goes to Settings ▸ Models
// with the draft kept.
describe("Composer — the default model left the gateway's list", () => {
  const gone = (extra: Partial<Parameters<typeof Composer>[0]> = {}) =>
    props({
      modelReady: false,
      modelNotice: "default_model_gone",
      models: ["aigw:anthropic/claude-haiku-4-5"],
      ...extra,
    });

  it("asks for a choice instead of offering the dead id, and says why", () => {
    stubFetch();
    render(<Composer {...gone()} />);
    expect(screen.getByTestId("model-default-gone").textContent).toBe(
      "Your previous default model is no longer on your available list — please choose another.",
    );
    const chip = screen.getByText("Choose a model").closest("button")!;
    expect(chip.getAttribute("title")).toContain("no longer on your available list");
    // No picker, so the dead model cannot be picked (or sent on) from here.
    expect(screen.queryByTitle(/Claude Fable 5/)).toBeNull();
    expect(screen.queryByText("No model")).toBeNull();
  });

  it("routes the chip and a send to model setup, keeping the draft", () => {
    stubFetch();
    const onConnectModel = vi.fn();
    const onSend = vi.fn();
    render(<Composer {...gone({ onConnectModel, onSend })} />);
    fireEvent.click(screen.getByText("Choose a model"));
    expect(onConnectModel).toHaveBeenCalledTimes(1);
    const box = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "draft to keep" } });
    fireEvent.click(screen.getByLabelText("Send"));
    expect(onSend).not.toHaveBeenCalled();
    expect(onConnectModel).toHaveBeenCalledTimes(2);
    expect(box.value).toBe("draft to keep");
  });

  it("keeps the plain 'No model' chip when nothing is connected at all", () => {
    stubFetch();
    render(<Composer {...props({ modelReady: false })} />);
    expect(screen.getByText("No model")).toBeTruthy();
    expect(screen.queryByTestId("model-default-gone")).toBeNull();
    expect(screen.queryByText("Choose a model")).toBeNull();
  });

  it("shows the notice in Chinese with the agreed wording", async () => {
    stubFetch();
    const i18n = (await import("i18next")).default;
    await i18n.changeLanguage("zh");
    try {
      render(<Composer {...gone()} />);
      expect(screen.getByTestId("model-default-gone").textContent).toBe(
        "原默认模型已不在可用清单，请重新选择",
      );
      expect(screen.getByText("选择模型")).toBeTruthy();
    } finally {
      await i18n.changeLanguage("en");
    }
  });
});
