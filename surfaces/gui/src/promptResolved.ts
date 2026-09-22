import i18n from "./i18n";
import type { Item } from "./types";

// A pending gate (approval / ask_user / directory grant / plan / tool install) can now be
// answered somewhere other than this app: the WeChat mirror of the same Inbox item, or the
// 30-minute expiry watchdog behind it (`manager._expire_weixin_prompt`). Either way the
// server pushes `prompt_resolved` and the inline card DISAPPEARS — every one of those cards
// renders only while `!item.resolved` (App.tsx's pending* selectors), so there is no resolved
// state of the card left to annotate. The record therefore goes into the transcript, where it
// stays: without it the gate the user was looking at just blinks out with no explanation.
//
// Pure on purpose (the `modeNotice.ts` precedent): App.tsx's WS switch has no test harness,
// so the wording and the allow/deny reading live here where `promptResolved.test.ts` pins
// them.

/** A structured resolution — directory / plan / tool carry theirs as a JSON string. */
function verdict(resolution: string): { granted?: boolean; approved?: boolean } {
  try {
    const parsed = JSON.parse(resolution);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

// An ask_user answer is the user's own words, and a long free-text one would swamp the line.
const MAX_ANSWER = 60;

/** What the other surface decided, in one human phrase: the allow/deny word for the gates
 *  that are yes-or-no, the answer itself for an ask_user question. Mirrors the server's
 *  `interactions.outcome_text`, which reads the same verdict fields for the WeChat receipt —
 *  neither side matches resolution strings literally, because the real ones diverge (a typed
 *  folder path, "Approve and run" sending mode="bypass-approvals"). */
export function promptOutcome(kind: string, resolution: string): string {
  if (kind === "question") {
    const answer = resolution.trim();
    if (!answer) return i18n.t("transcript.resolved_outcome_deny");
    return answer.length > MAX_ANSWER ? answer.slice(0, MAX_ANSWER) + "…" : answer;
  }
  const allowed =
    kind === "approval"
      ? resolution === "allow"
      : kind === "directory"
        ? !!verdict(resolution).granted
        : !!verdict(resolution).approved;
  return i18n.t(
    allowed ? "transcript.resolved_outcome_allow" : "transcript.resolved_outcome_deny",
  );
}

/** The transcript line for a gate answered elsewhere, or null when this app answered it
 *  (`via: "app"` is never broadcast) or the surface is one we have no wording for. */
export function promptResolvedNotice(
  kind: string,
  via: string,
  resolution: string,
): Item | null {
  if (via === "timeout")
    return { kind: "notice", tone: "warn", text: i18n.t("transcript.resolved_timed_out") };
  if (via !== "weixin") return null;
  return {
    kind: "notice",
    tone: "info",
    text: i18n.t("transcript.resolved_via_weixin", {
      outcome: promptOutcome(kind, resolution),
    }),
  };
}

/** The transcript line for an answer that came in after the conversation had already moved
 *  past its prompt — the server's `answer_superseded` (manager `_note_superseded_answer`): a
 *  durable resume found the answered call no longer at the end of the transcript, so nothing
 *  ran for it, while the Inbox shows the prompt resolved. Persisted server-side, so the live
 *  event and a reload both come through here. `warn`, not `info`: it reports something the
 *  user asked for that did not happen — and so, like the server's own retry guard, it is not
 *  looked through when `retryAnchor` searches for a Retry button behind it. */
export function answerSupersededNotice(
  prompt: string,
  resolution: string,
  tool?: string,
): Item {
  const outcome = promptOutcome(prompt, resolution);
  return {
    kind: "notice",
    tone: "warn",
    text: tool
      ? i18n.t("transcript.answer_superseded_tool", { tool, outcome })
      : i18n.t("transcript.answer_superseded", { outcome }),
  };
}
