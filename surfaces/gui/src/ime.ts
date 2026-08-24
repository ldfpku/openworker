// Input-method composition guard.
//
// A keydown that arrives while an input method is composing belongs to the IME, not to us.
// Typing Chinese means: type pinyin, pick a candidate, commit it. The keys that drive that
// candidate list are Enter (commit), ArrowUp/ArrowDown (move), and Escape (cancel) — every
// one of which is also a shortcut somewhere in this app. Acting on them mid-composition
// sends half-finished messages, which is worse than an annoyance: the message is gone.
//
// Three signals, because no single one holds across both webviews we ship:
//
//   1. `isComposing` on the event — the standard, and the one that matters most here.
//      Chromium (WebView2 on Windows) sets it on the very keydown that commits a candidate.
//   2. `keyCode === 229` — the legacy sentinel browsers report for "this key went to the
//      IME". Cheap to check and still emitted by some input methods.
//   3. a short tail after `compositionend` — WebKit (WKWebView on macOS) has historically
//      dispatched compositionend BEFORE the committing keydown, so `isComposing` is already
//      false on the one event we need to catch. Those two land in the same task; a human
//      pressing Enter twice (commit, then send) is an order of magnitude slower. The window
//      is deliberately tiny — stretching it would start swallowing real sends.
//
// The failure modes are not symmetric, and that asymmetry decided the design: guarding one
// keystroke too many costs a second Enter press, while guarding one too few fires off an
// unfinished message to a coworker. When in doubt this errs toward not acting.

/** How long after compositionend a keydown is still treated as the IME's. */
const COMPOSITION_TAIL_MS = 50;

let composing = false;
let endedAt = 0;

/**
 * Listen for composition at the document level, once, so individual inputs don't each have to
 * wire onCompositionStart/onCompositionEnd. Composition events bubble, so one pair covers every
 * field in the app. Call alongside initLocale() before the first render.
 */
export function initIme() {
  if (typeof document === "undefined") return;
  document.addEventListener(
    "compositionstart",
    () => {
      composing = true;
    },
    true,
  );
  document.addEventListener(
    "compositionend",
    () => {
      composing = false;
      endedAt = Date.now();
    },
    true,
  );
}

type AnyKeyEvent =
  | KeyboardEvent
  | { nativeEvent?: KeyboardEvent; isComposing?: boolean; keyCode?: number };

/**
 * True when this keydown belongs to an in-flight input-method composition and the app should
 * keep its hands off it. Guard every Enter/Escape/Arrow shortcut that reads from a text field.
 */
export function isComposing(e: AnyKeyEvent): boolean {
  const native = ("nativeEvent" in e && e.nativeEvent ? e.nativeEvent : e) as KeyboardEvent;
  if (native?.isComposing) return true;
  if (native?.keyCode === 229) return true;
  if (composing) return true;
  if (endedAt === 0 || Date.now() - endedAt >= COMPOSITION_TAIL_MS) return false;

  // Tail case only. Composition has already ended, so the input method has no further use for
  // this key — but the browser does: left alone, a swallowed Enter reaches the textarea as a
  // newline. Committing a candidate with Space and then reaching for Enter inside the tail is
  // the one sequence that lands here wrongly, and eating the default action is what keeps its
  // cost at "press Enter again" rather than "a blank line appeared in your message".
  // Deliberately NOT done in the branches above: while composition is genuinely in flight the
  // input method still needs the key, and cancelling the default action can break the commit.
  (e as { preventDefault?: () => void }).preventDefault?.();
  return true;
}

/** Test seam: forget any composition state left over from a previous case. */
export function resetImeForTest() {
  composing = false;
  endedAt = 0;
}
