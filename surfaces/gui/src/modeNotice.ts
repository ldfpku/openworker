import i18n from "./i18n";

// coworker/permissions.py MODE_LABELS — the human label baked into the persisted "<label> is
// on." marker. app.py's `set_mode` handler appends it two ways: as a bare `mode_switch` notice
// (`f"{label} is on."`) on every later switch, and as the `mode_notice` explainer's own title
// the FIRST time a session enters Auto-Approve ("Auto-approve is on.", same shape). Both are
// persisted verbatim in English and replayed as-is on reload, so old sessions carry this text
// baked in forever — we can't localize it by changing the generator, only by translating it
// here at display time.
//
// Reuses the exact Chinese words the Composer's mode picker already shows for the same modes
// (composer.mode.* — Composer.tsx's own `modeLabel()` comment says as much: "so the
// transcript's mode markers read the same names the user just chose from") rather than
// inventing separate wording that could drift from the picker.
const MODE_LABEL_KEYS: Record<string, string> = {
  Discuss: "composer.mode.discuss",
  Plan: "composer.mode.plan",
  "Ask for approval": "composer.mode.interactive",
  "Bypass approvals": "composer.mode.auto",
  "Auto-approve": "composer.mode.auto_approve",
};

const MODE_ON_RE = /^(.+) is on\.$/;

/**
 * "<label> is on." -> localized, for any label MODE_LABELS actually produces. Anything else
 * (an unrecognized label, or text that just happens to end the same way) renders unchanged —
 * this must never rewrite text it doesn't recognize as one of the five known mode labels.
 */
export function modeOnText(raw: string): string {
  const match = MODE_ON_RE.exec(raw);
  const key = match ? MODE_LABEL_KEYS[match[1]] : undefined;
  return key ? i18n.t("app.notice.mode_on", { label: i18n.t(key) }) : raw;
}

// coworker/permissions.py AUTO_APPROVE_NOTICE, verbatim — the once-per-session Auto-Approve
// explainer body persisted alongside the "Auto-approve is on." mode_notice title.
const AUTO_APPROVE_BODY =
  "Auto-approve uses a model to let routine actions through without asking; anything " +
  "it isn't sure about still comes to you. It cuts interruptions but still carries " +
  "some risk i.e. a command it allows still reaches anything you can. These are model " +
  "judgments, and not guarantees.";

/** The mode_notice explainer body: localized on an exact match, unchanged otherwise. */
export function modeNoticeBody(raw: string): string {
  return raw === AUTO_APPROVE_BODY ? i18n.t("app.notice.auto_approve_explainer") : raw;
}

// coworker/engine.py _REVIEWER_PAUSED_TEXT (§8.4 breaker): persisted as a `reviewer_paused`
// notice when the auto-approve reviewer blocks too many actions in a row. The count is a
// module constant today but travels through the sentence, so match it as data rather than
// baking today's value into the pattern.
const REVIEWER_PAUSED_RE =
  /^Auto-approve is paused for the rest of this turn — the reviewer blocked (\d+) actions in a row, so approvals now come to you\.$/;

/** The reviewer-paused breaker notice: localized when it matches the known shape, unchanged
 *  otherwise (an empty string included — callers fall back to their own default for that). */
export function reviewerPausedText(raw: string): string {
  const match = REVIEWER_PAUSED_RE.exec(raw);
  return match ? i18n.t("app.notice.reviewer_paused", { n: match[1] }) : raw;
}

// coworker/engine.py switch_model: "Model switched to {label}", plus an optional
// " — earlier images can't be read by this model" suffix when the new model lacks vision.
// The label is the model's display name (matrix.py `model_labels()`, falling back to the
// raw id) — it travels through the sentence as data, so only the scaffold is translated.
const MODEL_SWITCH_RE =
  /^Model switched to (.+?)( — earlier images can't be read by this model)?$/;

/** The mid-session model-switch marker: scaffold localized, model label kept verbatim;
 *  unrecognized text renders unchanged. */
export function modelSwitchText(raw: string): string {
  const match = MODEL_SWITCH_RE.exec(raw);
  if (!match) return raw;
  const base = i18n.t("app.notice.model_switched_to", { label: match[1] });
  return match[2] ? base + i18n.t("app.notice.model_switched_no_vision") : base;
}

// coworker/engine.py `_compact_if_needed` (§ context compaction), two return values persisted
// verbatim as a `{"role":"notice","kind":"compacted","text":…}` marker and replayed as-is on
// reload — same reasoning as everything above: the generator can't be changed without leaving
// every already-persisted notice stuck in English, so this only translates at display time.
//   engine.py:712  "Context compacted — earlier turns were summarized"        (state built OK)
//   engine.py:718  "Context trimmed — oldest turns dropped (summary unavailable)"  (fallback)
const COMPACTED_SUMMARIZED = "Context compacted — earlier turns were summarized";
const COMPACTED_TRIMMED = "Context trimmed — oldest turns dropped (summary unavailable)";

/** The compaction/trim divider notice: localized on an exact match of one of the two known
 *  engine outcomes, unchanged otherwise (including the empty string — callers fall back to
 *  their own default for that). */
export function compactionText(raw: string): string {
  if (raw === COMPACTED_SUMMARIZED) return i18n.t("app.notice.context_compacted_summarized");
  if (raw === COMPACTED_TRIMMED) return i18n.t("app.notice.context_trimmed");
  return raw;
}

// coworker/engine.py `_compact_if_needed` (engine.py:684-696): when the summarizer can't
// condense a session's history, the engine asks the user how to proceed via `question_asker`
// (ask_user). This prompt is live-only — never persisted — but its *answer value* is compared
// literally server-side (engine.py:701, `answer.get("answer") != "Retry"`), so unlike the
// notices above we must NOT rewrite the string that travels back to the server: only the
// question, header, and option *display* text are translated here; callers must still send the
// raw English option value (e.g. "Retry") back to the engine.
const COMPACTION_QUESTION =
  "Context compaction failed — the summarizer couldn't condense this session's history. How " +
  "should I proceed?";
const COMPACTION_HEADER = "Compaction";
const COMPACTION_OPTION_KEYS: Record<string, string> = {
  Retry: "app.notice.compaction_retry",
  "Trim oldest 10%": "app.notice.compaction_trim",
};

/** The compaction-failed question body: localized on an exact match, unchanged otherwise. */
export function compactionQuestionText(raw: string): string {
  return raw === COMPACTION_QUESTION ? i18n.t("app.notice.compaction_failed_question") : raw;
}

/** The compaction-failed question's header chip ("Compaction"): localized on an exact match,
 *  unchanged otherwise. */
export function compactionHeaderText(raw: string): string {
  return raw === COMPACTION_HEADER ? i18n.t("app.notice.compaction_header") : raw;
}

/** One of the compaction-failed question's options ("Retry" / "Trim oldest 10%"): localized
 *  *for display only* on an exact match, unchanged otherwise. The raw value passed in here must
 *  still be what's sent back to the server — never the return value of this function. */
export function compactionOptionLabel(raw: string): string {
  const key = COMPACTION_OPTION_KEYS[raw];
  return key ? i18n.t(key) : raw;
}
