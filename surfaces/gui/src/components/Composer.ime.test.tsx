// Typing Chinese means composing: type pinyin, then press Enter to commit the candidate.
// That commit-Enter reaches the composer as a keydown, and until this was guarded it sent
// the half-finished message. Losing a draft to a stray Enter is not a papercut — the message
// is already gone to whoever was on the other end.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Composer } from "./Composer";
import { initIme, resetImeForTest } from "../ime";

initIme();

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("/skills")) return { ok: true, json: async () => ({ skills: [] }) } as Response;
      return { ok: true, json: async () => ({}) } as Response;
    }),
  );
}

const props = (extra: Partial<Parameters<typeof Composer>[0]> = {}) => ({
  mode: "interactive",
  model: "gpt-5.6-sol",
  running: false,
  connected: true,
  sessionId: "s1",
  onSend: vi.fn(),
  onInterrupt: vi.fn(),
  onModeChange: vi.fn(),
  onModelChange: vi.fn(),
  ...extra,
});

const box = () => screen.getByPlaceholderText(/Ask the coworker/);

afterEach(() => {
  cleanup();
  resetImeForTest();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("Composer + input method", () => {
  it("does not send when Enter commits an IME candidate", () => {
    stubFetch();
    const p = props();
    render(<Composer {...p} />);
    fireEvent.change(box(), { target: { value: "你好" } });
    // Chromium flags the committing keydown; this is the Windows/WebView2 path.
    fireEvent.keyDown(box(), { key: "Enter", isComposing: true });
    expect(p.onSend).not.toHaveBeenCalled();
  });

  it("does not send on the Enter that lands right after compositionend", () => {
    // WebKit dispatches compositionend first, so the commit-Enter looks ordinary.
    stubFetch();
    const p = props();
    render(<Composer {...p} />);
    fireEvent.change(box(), { target: { value: "你好" } });
    fireEvent.compositionStart(box());
    fireEvent.compositionEnd(box());
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(p.onSend).not.toHaveBeenCalled();
  });

  it("still sends on a real Enter", async () => {
    // The guard must not cost everyone else their Enter key.
    stubFetch();
    const p = props();
    render(<Composer {...p} />);
    fireEvent.change(box(), { target: { value: "你好" } });
    fireEvent.compositionStart(box());
    fireEvent.compositionEnd(box());
    await new Promise((r) => setTimeout(r, 80)); // past the tail: this Enter is the user's
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(p.onSend).toHaveBeenCalledWith("你好", [], undefined);
  });

  it("sends normally when no input method is involved at all", () => {
    stubFetch();
    const p = props();
    render(<Composer {...p} />);
    fireEvent.change(box(), { target: { value: "hello" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(p.onSend).toHaveBeenCalledWith("hello", [], undefined);
  });

  it("leaves the arrow keys to the candidate list while the slash menu is open", () => {
    // "/" opens the force-run picker, which binds ↑/↓/Enter/Escape — exactly the keys an IME
    // uses to walk its candidates. Mid-composition those belong to the IME.
    stubFetch();
    const p = props();
    render(<Composer {...p} />);
    fireEvent.change(box(), { target: { value: "/" } });
    fireEvent.keyDown(box(), { key: "Escape", isComposing: true });
    // Escape would have cleared the draft; composing means it never reached us.
    expect((box() as HTMLTextAreaElement).value).toBe("/");
  });
});
