// Maps the raw transcript from GET /v1/sessions/{id}/messages into the GUI's `Item[]` model.
// Extracted from App.tsx so it can be unit-tested without standing up the whole app.
//
// A connector-delivered user message carries a structured `source` sidecar (§3.1); when present it
// becomes a `connector` item (rendered as ConnectorMessageCard) instead of a plain user bubble. This
// generalizes to any connector via the registry — no Slack special-casing here.

import type { ConversationMessage } from "./api";
import i18n from "./i18n";
import type { Attachment, Item } from "./types";
import {
  compactionText,
  modelSwitchText,
  modeNoticeBody,
  modeOnText,
  reviewerPausedText,
  turnAbortedText,
  turnRetryText,
  turnTruncatedText,
} from "./modeNotice";
import { answerSupersededNotice } from "./promptResolved";

// i18n.t() returns undefined before init() (bare unit tests call this mapper without
// initLocale(); the app always inits in main.tsx). Mirror react-i18next's graceful
// fallback: return the English key itself, with {{placeholders}} interpolated.
const t = (key: string, opts?: Record<string, unknown>): string =>
  i18n.isInitialized
    ? i18n.t(key, opts)
    : key.replace(/\{\{(\w+)\}\}/g, (_, v: string) => String(opts?.[v] ?? ""));

export function itemsFromMessages(messages: ConversationMessage[]): Item[] {
  const items: Item[] = [];
  // Index tool results by tool_call_id so replayed tool rows can show their output
  // (the live view gets this from `tool_finished` events; on replay it's the `role:"tool"` msgs).
  const results: Record<string, string> = {};
  // `_display` sidecar on a tool message = user-facing metadata the agent never saw
  // (e.g. how many hits the privacy filters hid) — surfaces on the tool card.
  const hiddenCounts: Record<string, number> = {};
  // Approval provenance (owner ruling 2026-08-24): who cleared (or refused) the call —
  // "reviewer"/"bypass"/"user"/"reviewer_denied" — persisted in the same sidecar so the
  // quiet chips survive reload.
  const approvalMeta: Record<string, { origin: string; note?: string; grant?: string }> = {};
  for (const m of messages || []) {
    if (m.role === "tool" && m.tool_call_id) {
      results[m.tool_call_id] =
        typeof m.content === "string" ? m.content : JSON.stringify(m.content);
      const hidden = Number(m._display?.hidden_by_filters || 0);
      if (hidden > 0) hiddenCounts[m.tool_call_id] = hidden;
      if (m._display?.approval_origin)
        approvalMeta[m.tool_call_id] = {
          origin: String(m._display.approval_origin),
          ...(m._display.approval_note ? { note: String(m._display.approval_note) } : {}),
          ...(m._display.approval_grant ? { grant: String(m._display.approval_grant) } : {}),
        };
    }
  }
  for (const m of messages || []) {
    if (m.role === "user") {
      // Connector message → structured card; the framed `content` stays for the model, but display
      // renders from the source sidecar.
      if (m.source?.connector) {
        items.push({ kind: "connector", source: m.source });
        continue;
      }
      const user = userItemFromContent(m.content);
      // Force-run (`/skill …`): `_display` holds the user's literal line; `content` carries
      // the model-facing framing. Render what the user typed — one truthful bubble.
      if (typeof m._display === "string" && m._display) user.text = m._display;
      // `ts` (unix seconds) is the server's canonical-message stamp; older sessions have none.
      if (typeof m.ts === "number") user.ts = m.ts;
      if (user.text || user.attachments?.length) items.push(user);
    } else if (m.role === "assistant") {
      if (m.content || m.reasoning)
        items.push({
          kind: "assistant",
          text: m.content || "",
          ...(typeof m.ts === "number" ? { ts: m.ts } : {}),
          ...(m.reasoning ? { reasoning: m.reasoning } : {}),
        });
      for (const tc of m.tool_calls || []) {
        let args: any = {};
        try {
          args = JSON.parse(tc.function?.arguments || "{}");
        } catch {
          args = {};
        }
        const preview = results[tc.id];
        const hidden = hiddenCounts[tc.id];
        const meta = approvalMeta[tc.id];
        // A denial (by the reviewer or the user) must not replay as a green step.
        const denied = meta && (meta.origin === "reviewer_denied" || meta.grant === "deny");
        items.push({
          kind: "tool",
          id: tc.id,
          name: tc.function?.name,
          args,
          status: denied ? "denied" : "ok",
          preview,
          ...(hidden ? { hidden } : {}),
          ...(meta ? { approvalOrigin: meta.origin } : {}),
          ...(meta?.note
            ? meta.origin === "reviewer_denied"
              ? { reviewerReason: meta.note }
              : { approvalNote: meta.note }
            : {}),
          ...(meta?.grant ? { approvalGrant: meta.grant } : {}),
        });
      }
    } else if (m.role === "notice") {
      // Persisted markers (engine `_append_notice`): error/interrupted/model-switch survive
      // reload exactly like the live view rendered them. An error notice is retriable —
      // the Transcript only offers the button when it's the transcript tail.
      items.push(
        m.kind === "interrupted"
          ? { kind: "notice", tone: "warn", text: t("Interrupted.") }
          : m.kind === "model_switch"
            ? // Bookkeeping (matches the live `model_changed` handler): a model picked
              // before the first message is a setting, and must not end the draft phase.
              { kind: "notice", tone: "info", text: m.text ? modelSwitchText(m.text) : t("Model switched"), bookkeeping: true }
            : m.kind === "compacted"
              ? // The subtle "compacted here" divider (OPE-27) — the transcript itself is intact.
                { kind: "notice", tone: "info", text: compactionText(m.text || "") || t("Context compacted") }
              : m.kind === "mcp_error"
                ? // A configured MCP server failed to start for this session — informational,
                  // NOT retriable (retry re-runs the model turn, which can't fix a dead server).
                  // Renders as one quiet line + disclosure. Legacy notices (persisted before
                  // the `server` field existed) recover the name from their own text, so old
                  // transcripts collapse too instead of keeping the wall of stderr.
                  mcpNoticeItem(m)
                : m.kind === "project_presence"
                  ? // Grant-time pointer (pass 20): the granted folder already has
                    // memory/board — informational, one quiet line.
                    { kind: "notice", tone: "info", text: m.text || "" }
                  : m.kind === "reviewer_paused"
                    ? // §8.4 breaker: auto-approve paused itself for the rest of the turn.
                      // The literal fallback covers records with a missing text field only;
                      // it won't match reviewerPausedText's pattern and renders as-is.
                      {
                        kind: "notice",
                        tone: "info",
                        text: reviewerPausedText(
                          m.text || "Auto-approve paused for the rest of this turn."
                        ),
                      }
                    : m.kind === "mode_notice"
                      ? // The once-per-session Auto-Approve explainer, in place forever. Server-
                        // authored English, persisted verbatim — localized at display time (same
                        // reasoning as the session-title sentinel: the generator can't change
                        // without leaving every already-persisted notice stuck in English).
                        // `bookkeeping` must match the live WS handler's (App.tsx `mode_notice`),
                        // or a resumed draft would read as a started conversation.
                        {
                          kind: "notice",
                          tone: "info",
                          title: modeOnText((m as any).title || "Auto-approve is on."),
                          text: modeNoticeBody(m.text || ""),
                          bookkeeping: true,
                        }
                      : m.kind === "mode_switch"
                        ? { kind: "notice", tone: "info", text: modeOnText(m.text || ""), bookkeeping: true }
                        : CUT_OFF_NOTICE_KINDS.has(String(m.kind))
                          ? cutOffNoticeItem(m)
                          : m.kind === "answer_superseded"
                            ? // An Inbox answer that came in after the conversation moved past its
                              // prompt: nothing ran for it. Not an error, and not retriable
                              // itself; `retryAnchor` looks through it to an error before it
                              // (`retryTransparent`).
                              answerSupersededNotice(
                                String(m.prompt || ""),
                                String(m.resolution ?? ""),
                                m.tool ? String(m.tool) : undefined,
                              )
                            : {
                                kind: "notice",
                                tone: "warn",
                                text: t("Error: {{message}}", { message: m.text || t("unknown") }),
                                retriable: true,
                              },
      );
    }
    // system messages are omitted; tool-result messages are folded into the tool row above
  }
  return items;
}

// engine.py's three "the provider cut this turn short" markers, in one helper rather than
// three more arms on a chain that is already ten ternaries deep. All three carry a
// structured `reason` beside the server's English sentence, so each localizes from the
// reason and falls back to that sentence for a reason it doesn't recognize.
const CUT_OFF_NOTICE_KINDS = new Set(["turn_aborted", "turn_truncated", "turn_retry"]);

function cutOffNoticeItem(m: ConversationMessage): Item {
  // Nothing came back at all: reported exactly like a provider failure, Retry and all.
  // No "Error: " scaffold — the text is already a whole sentence.
  if (m.kind === "turn_aborted")
    return {
      kind: "notice",
      tone: "warn",
      text: turnAbortedText(m.reason, m.text || "", m.retries),
      retriable: true,
    };
  // An answer DID arrive and the turn completed; this only warns that it may be missing
  // its tail, so it is NOT retriable — retrying would re-answer a finished turn.
  if (m.kind === "turn_truncated")
    return { kind: "notice", tone: "warn", text: turnTruncatedText(m.reason, m.text || "") };
  // One automatic re-run of a call that never landed. Quiet: the turn it belongs to may
  // well have gone on to succeed, so it must not read as a failure — and the `info` tone
  // is what keeps it from consuming the Retry button on the notice that follows it.
  return {
    kind: "notice",
    tone: "info",
    text: turnRetryText(m.reason, m.attempt, m.max, m.text || ""),
  };
}

function mcpNoticeItem(m: ConversationMessage): Item {
  const text = typeof m.text === "string" ? m.text : "";
  const server =
    (m.server && String(m.server)) || (text.match(/MCP server [“"]([^”"]+)[”"]/) || [])[1];
  if (!server)
    return { kind: "notice", tone: "warn", text: text || "An MCP server failed to start" };
  // The old format appended a plain-text Settings pointer — the button replaces it.
  const detail = text.replace(/\s*—\s*see Settings ▸ Connectors\s*$/u, "");
  return {
    kind: "notice",
    tone: "warn",
    text: `MCP server “${server}” didn’t start — its tools are unavailable here`,
    server,
    detail: detail || undefined,
  };
}

export function userItemFromContent(content: any): Extract<Item, { kind: "user" }> {
  if (typeof content === "string") return { kind: "user", text: content };
  if (!Array.isArray(content)) return { kind: "user", text: "" };

  const text: string[] = [];
  const attachments: Attachment[] = [];
  for (const part of content) {
    if (!part || typeof part !== "object") continue;
    if (part.type === "text" && part.text) {
      text.push(String(part.text));
    } else if (part.type === "image_url") {
      const url = part.image_url?.url;
      if (typeof url === "string" && url.startsWith("data:image/")) {
        attachments.push({ kind: "image", name: "image", data_url: url });
      }
    }
  }
  return { kind: "user", text: text.join("\n\n"), attachments };
}
