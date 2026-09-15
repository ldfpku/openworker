// The model picker's badge slot. An Option carries exactly ONE badge, and two facts now
// compete for it: "free" (nvidia/ollama — costs nothing per token) and "has a same-tier
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
  "nvidia:qwen3-coder",
];

const props = (extra: Partial<Parameters<typeof Composer>[0]> = {}) => ({
  mode: "interactive",
  model: "aigw:anthropic/claude-fable-5",
  models: MODELS,
  modelLabels: {
    "aigw:anthropic/claude-fable-5": "Claude Fable 5 · via Cloudflare",
    "aigw:anthropic/claude-haiku-4-5": "Claude Haiku 4.5 · via Cloudflare",
    "nvidia:qwen3-coder": "Qwen3 Coder · via NVIDIA",
  },
  modelFallbacks: {
    "aigw:anthropic/claude-fable-5": "GPT-5.6 Sol · via Cloudflare",
    "nvidia:qwen3-coder": "GPT-5.6 Terra · via Cloudflare",
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

/** Open the picker and return the row whose label starts with `text`. */
function openRow(text: string): HTMLElement {
  fireEvent.click(screen.getByTitle(/Claude Fable 5/));
  const row = screen
    .getAllByText((_c, el) => el?.className === "dd-label")
    .find((el) => el.textContent?.includes(text));
  if (!row) throw new Error(`no picker row for ${text}`);
  return row as HTMLElement;
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
