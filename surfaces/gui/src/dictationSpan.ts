// The composer's dictation span: the stretch of the draft that live transcription owns.
//
// Live transcription is not append-only typing. Every update the engine sends is the WHOLE
// transcript so far, and the final transcript re-transcribes the recording from scratch and
// replaces it. So the composer cannot simply insert characters as they arrive — it has to keep
// a region of the textarea reserved, replace that region wholesale on every update, and leave
// everything around it alone.
//
// That region is a span: `before` + `text` + `after`. Recording starts by splitting the draft at
// the caret; `text` is whatever the engine last said; `before`/`after` are the user's own words
// on each side. The user keeps the keyboard the whole time, which is what the rest of this
// module is about:
//
//   * an edit OUTSIDE the span (typing ahead of it, fixing a typo behind it) just moves the
//     boundary — live text keeps landing in the same place;
//   * an edit INSIDE the span means the user has taken the words over. Overwriting them on the
//     next update would delete what they just typed, so the span DETACHES: it stops tracking,
//     and the final transcript is appended at the end rather than dropped on top of their edit.
//
// Everything here is pure: no React, no DOM. The composer owns the textarea and the caret; this
// module owns the arithmetic, which is where the bugs would otherwise live.

export type DictationSpan = {
  /** The draft to the left of the span. */
  before: string;
  /** The draft to the right of the span. */
  after: string;
  /** What the engine last said — replaced wholesale, never extended. */
  text: string;
  /** The user edited inside the span; live updates no longer overwrite it. A detached span
   * keeps the whole draft in `before` so `spanValue` still matches what is on screen. */
  detached: boolean;
  /** `beginSpan` inserted a separating space; cancelling takes it back out again. */
  separator: boolean;
};

/** Give up on tracking: the draft is the user's now, verbatim. */
const detach = (span: DictationSpan, value: string): DictationSpan => ({
  before: value,
  after: "",
  text: "",
  detached: true,
  separator: span.separator,
});

/** True when `value` ends in something a new sentence should not be glued onto. */
const endsOpen = (value: string) => value.length === 0 || /\s$/.test(value);

/**
 * Split the draft at the caret and reserve the gap between the halves.
 *
 * A space is inserted when the left half ends mid-word, so dictating into "会议纪要" does not
 * produce "会议纪要今天的会议". Nothing is added on the right: the final transcript ends in
 * punctuation, and the user can see where their own text resumes.
 */
export function beginSpan(value: string, caret: number): DictationSpan {
  const at = Math.max(0, Math.min(caret, value.length));
  const head = value.slice(0, at);
  const separator = !endsOpen(head);
  return {
    before: separator ? `${head} ` : head,
    after: value.slice(at),
    text: "",
    detached: false,
    separator,
  };
}

/** The whole textarea value this span currently describes. */
export function spanValue(span: DictationSpan): string {
  return span.before + span.text + span.after;
}

/** Where the caret belongs after an update: at the end of the dictated text, not of the draft. */
export function spanCaret(span: DictationSpan): number {
  return span.before.length + span.text.length;
}

/** Take a live update. A detached span ignores it — the user's edit wins. */
export function applyPartial(span: DictationSpan, text: string): DictationSpan {
  if (span.detached) return span;
  if (text === span.text) return span;
  return { ...span, text };
}

/**
 * Fold a user edit back into the span, given the textarea's new value.
 *
 * The edited region is located by trimming the common prefix and suffix. Landing wholly to one
 * side of the span moves that side's boundary; touching the span detaches it. With no live text
 * yet the span is a zero-width point: `changeEnd === spanStart` there, so an edit landing exactly
 * on it is taken as being BEHIND the span and joins `before` — the dictated words then land after
 * what the user just typed, following the caret, which is where they would have gone had the
 * words arrived first.
 *
 * Repeated text can make the common-affix trim attribute an edit to the wrong side (deleting one
 * of two identical words). The cost is a span that detaches when it did not have to, which is
 * the safe direction: it only ever declines to overwrite.
 */
export function reconcileUserEdit(span: DictationSpan, nextValue: string): DictationSpan {
  // Already detached: keep mirroring the draft so finalize and cancel still see what is on screen.
  if (span.detached) return nextValue === span.before ? span : detach(span, nextValue);
  const current = spanValue(span);
  if (nextValue === current) return span;

  let prefix = 0;
  const shortest = Math.min(current.length, nextValue.length);
  while (prefix < shortest && current[prefix] === nextValue[prefix]) prefix += 1;
  let suffix = 0;
  while (
    suffix < shortest - prefix &&
    current[current.length - 1 - suffix] === nextValue[nextValue.length - 1 - suffix]
  ) {
    suffix += 1;
  }

  const spanStart = span.before.length;
  const spanEnd = spanStart + span.text.length;
  const changeStart = prefix;
  const changeEnd = current.length - suffix;

  if (changeEnd <= spanStart) {
    // Behind the span: everything up to the span is the new `before`.
    const beforeLength = nextValue.length - span.text.length - span.after.length;
    if (beforeLength < 0) return detach(span, nextValue);
    return { ...span, before: nextValue.slice(0, beforeLength) };
  }
  if (changeStart >= spanEnd) {
    // Ahead of the span: everything past the span is the new `after`.
    return { ...span, after: nextValue.slice(spanEnd) };
  }
  return detach(span, nextValue);
}

/**
 * Close the span with the final transcript.
 *
 * The final transcript REPLACES the live text — it is a fresh pass over the whole recording, not
 * a continuation, so appending it would say everything twice. Two exceptions:
 *
 *   * an empty final transcript leaves the live text alone (better a rough transcript than a
 *     draft that empties itself when the last pass finds nothing);
 *   * a detached span keeps the user's edit and takes the transcript at the end instead, so the
 *     recording is not silently thrown away.
 */
export function finalizeSpan(
  span: DictationSpan,
  finalText: string,
): { value: string; caret: number } {
  const transcript = finalText.trim();
  if (!transcript) {
    const value = spanValue(span);
    return { value, caret: span.detached ? value.length : spanCaret(span) };
  }
  if (span.detached) {
    const draft = spanValue(span);
    const value = endsOpen(draft) ? draft + transcript : `${draft} ${transcript}`;
    return { value, caret: value.length };
  }
  const closed: DictationSpan = { ...span, text: transcript };
  return { value: spanValue(closed), caret: spanCaret(closed) };
}

/**
 * Escape during a recording: the draft exactly as it stood before dictation started. The space
 * `beginSpan` inserted comes back out too — pressing Escape should leave no trace, not a stray
 * space the user never typed. A detached span is the user's own text by then, handed back whole.
 */
export function cancelSpan(span: DictationSpan): { value: string; caret: number } {
  if (span.detached) {
    const value = spanValue(span);
    return { value, caret: value.length };
  }
  const before =
    span.separator && span.before.endsWith(" ") ? span.before.slice(0, -1) : span.before;
  return { value: before + span.after, caret: before.length };
}
