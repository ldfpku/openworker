// The composition guard. What matters is that it says "hands off" on every shape of event a
// real input method produces, and that it stays out of the way for ordinary typing — a guard
// that fired on plain keystrokes would break Enter for everyone who doesn't use an IME.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initIme, isComposing, resetImeForTest } from "./ime";

// initIme() attaches its document listeners once; calling it here mirrors main.tsx.
initIme();

const key = (over: Record<string, unknown> = {}) =>
  ({
    key: "Enter",
    isComposing: false,
    keyCode: 13,
    preventDefault: vi.fn(),
    ...over,
  }) as unknown as KeyboardEvent;

/** A React synthetic event, which is what every call site actually passes. */
const synthetic = (over: Record<string, unknown> = {}) =>
  ({ key: "Enter", preventDefault: vi.fn(), nativeEvent: key(over) }) as never;

const compositionEvent = (type: string) => {
  const e = new Event(type, { bubbles: true });
  document.dispatchEvent(e);
};

beforeEach(() => resetImeForTest());
afterEach(() => resetImeForTest());

describe("isComposing", () => {
  it("lets an ordinary Enter through", () => {
    expect(isComposing(key())).toBe(false);
    expect(isComposing(synthetic())).toBe(false);
  });

  it("catches the committing Enter that Chromium flags — the Windows/WebView2 case", () => {
    // This is the one that matters most here: pressing Enter to choose a pinyin candidate.
    expect(isComposing(key({ isComposing: true }))).toBe(true);
    expect(isComposing(synthetic({ isComposing: true }))).toBe(true);
  });

  it("catches the legacy keyCode 229 sentinel", () => {
    expect(isComposing(key({ isComposing: false, keyCode: 229 }))).toBe(true);
  });

  it("catches keys pressed between compositionstart and compositionend", () => {
    // Covers a webview that reports neither isComposing nor 229 on keydown.
    compositionEvent("compositionstart");
    expect(isComposing(key())).toBe(true);
    compositionEvent("compositionend");
  });

  it("still guards briefly after compositionend — the WebKit ordering", () => {
    // Safari/WKWebView has dispatched compositionend BEFORE the committing keydown, so the
    // event that reaches us looks like a plain Enter. The tail is what catches it.
    compositionEvent("compositionstart");
    compositionEvent("compositionend");
    expect(isComposing(key())).toBe(true);
  });

  it("does not guard forever — a later Enter is the user's", async () => {
    // The tail must be short enough that "commit, then send" still sends.
    compositionEvent("compositionstart");
    compositionEvent("compositionend");
    await new Promise((r) => setTimeout(r, 80));
    expect(isComposing(key())).toBe(false);
  });

  it("eats the default action when — and only when — the tail is what caught the key", () => {
    // The tail is the one branch that can misfire on a key the user meant for us (commit a
    // candidate with Space, then reach for Enter inside 50ms). Swallowing the default action
    // is what keeps that mistake at "press Enter again" instead of "a blank line appeared in
    // your message" — left alone, the browser would put the Enter into the textarea.
    compositionEvent("compositionstart");
    compositionEvent("compositionend");
    const tail = key();
    expect(isComposing(tail)).toBe(true);
    expect(tail.preventDefault).toHaveBeenCalled();
  });

  it("leaves the default action alone while composition is genuinely in flight", () => {
    // Here the input method still needs the key to commit its candidate; cancelling the
    // default action can break that commit, so the guard must not touch it.
    const live = key({ isComposing: true });
    expect(isComposing(live)).toBe(true);
    expect(live.preventDefault).not.toHaveBeenCalled();
  });

  it("touches nothing once the tail has expired", async () => {
    compositionEvent("compositionstart");
    compositionEvent("compositionend");
    await new Promise((r) => setTimeout(r, 80));
    const later = key();
    expect(isComposing(later)).toBe(false);
    expect(later.preventDefault).not.toHaveBeenCalled();
  });

  it("is inert before any composition has ever happened", () => {
    // endedAt starts at 0; a naive `now - endedAt < TAIL` would be false here anyway, but a
    // sign-flip or a clock at the epoch must not make every keystroke look like an IME commit.
    expect(isComposing(key())).toBe(false);
  });
});
