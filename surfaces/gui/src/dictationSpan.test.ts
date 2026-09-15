// The dictation span's arithmetic, away from React. Every case here is a situation a user can
// reach with the keyboard while the microphone is open — the eight the plan calls out for §37.
import { describe, expect, it } from "vitest";
import {
  applyPartial,
  beginSpan,
  cancelSpan,
  finalizeSpan,
  reconcileUserEdit,
  spanCaret,
  spanValue,
  type DictationSpan,
} from "./dictationSpan";

/** Walk a span through a list of live updates, as the partial listener would. */
const stream = (span: DictationSpan, ...texts: string[]) =>
  texts.reduce((current, text) => applyPartial(current, text), span);

describe("dictation span", () => {
  it("dictating into an empty composer owns the whole draft", () => {
    const span = beginSpan("", 0);
    expect(span).toEqual({ before: "", after: "", text: "", detached: false, separator: false });
    expect(spanValue(applyPartial(span, "今天"))).toBe("今天");
  });

  it("dictating after a half-typed word keeps the two apart", () => {
    const span = beginSpan("会议纪要", 4);
    expect(span.before).toBe("会议纪要 ");
    expect(spanValue(applyPartial(span, "今天的会议"))).toBe("会议纪要 今天的会议");
    // Already separated: no second space piles up.
    expect(beginSpan("会议纪要 ", 5).before).toBe("会议纪要 ");
    expect(beginSpan("会议纪要\n", 5).before).toBe("会议纪要\n");
  });

  it("every update replaces the span instead of extending it", () => {
    const span = stream(beginSpan("", 0), "帮我把这个", "帮我把这个 pr", "帮我把这个 pr 的 ci");
    expect(spanValue(span)).toBe("帮我把这个 pr 的 ci");
    expect(spanCaret(span)).toBe("帮我把这个 pr 的 ci".length);
    // A shorter update (the engine revising the in-flight tail) must shrink the span, not
    // leave the longer text behind.
    expect(spanValue(applyPartial(span, "帮我把这个 pr"))).toBe("帮我把这个 pr");
  });

  it("dictating with the caret mid-draft leaves the tail where it was", () => {
    const span = beginSpan("开头 结尾", 3);
    expect(span.before).toBe("开头 ");
    expect(span.after).toBe("结尾");
    const live = applyPartial(span, "中间的话");
    expect(spanValue(live)).toBe("开头 中间的话结尾");
    expect(spanCaret(live)).toBe("开头 中间的话".length);
    expect(finalizeSpan(live, "中间的话。").value).toBe("开头 中间的话。结尾");
  });

  it("typing outside the span moves the boundary and keeps the live text flowing", () => {
    let span = applyPartial(beginSpan("开头 结尾", 3), "中间");
    // The user appends to the tail: "结尾" -> "结尾补充".
    span = reconcileUserEdit(span, "开头 中间结尾补充");
    expect(span.detached).toBe(false);
    expect(span.after).toBe("结尾补充");
    // And fixes the head: "开头 " -> "新开头 ".
    span = reconcileUserEdit(span, "新开头 中间结尾补充");
    expect(span.detached).toBe(false);
    expect(span.before).toBe("新开头 ");
    // Live text keeps landing between the two halves the user now owns.
    expect(spanValue(applyPartial(span, "中间的话"))).toBe("新开头 中间的话结尾补充");
  });

  it("editing inside the span detaches it so the user's words survive", () => {
    const live = applyPartial(beginSpan("开头 结尾", 3), "中间的话");
    const edited = reconcileUserEdit(live, "开头 中间的句子结尾");
    expect(edited.detached).toBe(true);
    // A detached span mirrors the draft verbatim, so the composer can keep asking it what is on
    // screen — writing the pre-edit value back would undo the user's correction.
    expect(spanValue(edited)).toBe("开头 中间的句子结尾");
    // Later updates no longer touch the draft.
    expect(spanValue(applyPartial(edited, "中间的话又长了一点"))).toBe("开头 中间的句子结尾");
    // Further typing keeps the mirror honest.
    expect(spanValue(reconcileUserEdit(edited, "开头 中间的句子结尾。"))).toBe("开头 中间的句子结尾。");
    // And the final transcript is appended rather than dropped on top of the edit.
    expect(finalizeSpan(edited, "中间的话。").value).toBe("开头 中间的句子结尾 中间的话。");
  });

  it("stopping replaces the live text, and an empty transcript changes nothing", () => {
    const live = stream(beginSpan("", 0), "今天的会议主要讨论三个问题");
    const done = finalizeSpan(live, "  今天的会议主要讨论三个问题。  ");
    expect(done.value).toBe("今天的会议主要讨论三个问题。");
    expect(done.caret).toBe(done.value.length);
    // Nothing recognised: keep the rough live text rather than emptying the draft.
    expect(finalizeSpan(live, "").value).toBe("今天的会议主要讨论三个问题");
    expect(finalizeSpan(live, "   ").value).toBe("今天的会议主要讨论三个问题");
  });

  it("typing before the first live update puts the dictated words after what was typed", () => {
    // The window between "start recording" and the first partial (~0.6 s of model latency) is
    // real, and a user can type into it. The span is zero-width there, so an edit lands exactly
    // ON it — `changeEnd === spanStart` — and the code reads that as behind the span: the typed
    // characters join `before`, and the dictation that arrives next follows the caret.
    const span = beginSpan("开头", 2);
    expect(span.text).toBe("");
    const typed = reconcileUserEdit(span, "开头 手打");
    expect(typed.detached).toBe(false);
    expect(typed.before).toBe("开头 手打");
    expect(spanValue(applyPartial(typed, "语音转写"))).toBe("开头 手打语音转写");
    // Same rule reading the other way: a zero-width span still sends an edit PAST it to `after`.
    const middle = beginSpan("开头 结尾", 3);
    const ahead = reconcileUserEdit(middle, "开头 结尾了");
    expect(ahead.after).toBe("结尾了");
    expect(spanValue(applyPartial(ahead, "语音"))).toBe("开头 语音结尾了");
  });

  it("cancelling restores the draft as it stood before the microphone opened", () => {
    const live = applyPartial(beginSpan("开头 结尾", 3), "中间的话");
    expect(cancelSpan(live)).toEqual({ value: "开头 结尾", caret: 3 });
    // The inserted separator goes with it: an untouched draft comes back byte for byte.
    expect(cancelSpan(applyPartial(beginSpan("会议纪要", 4), "今天")).value).toBe("会议纪要");
    // A detached span is the user's text now — cancelling must not delete it.
    const detached = reconcileUserEdit(live, "开头 中间的句子结尾");
    expect(cancelSpan(detached).value).toBe("开头 中间的句子结尾");
  });
});
