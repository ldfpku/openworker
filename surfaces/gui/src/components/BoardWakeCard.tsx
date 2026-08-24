// BoardWakeCard — a board wake in the lead's transcript, collapsed to ONE line by
// default (owner ruling 2026-08-16): most of the time the user just wants the
// feel that something is happening. Click to expand into per-event rows; long
// hand-off comments hide behind a per-row "show hand-off". NOT the connector
// card: a connector message is a foreign message, a board wake is a report —
// different shape, different affordances (they only share the visual family).
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { BoardWakeRow, MessageSource } from "../api";
import i18n from "../i18n";
import { Icon } from "./Icon";

// One key per English form (singular AND plural) so the English fallback stays
// byte-identical ("1 review" / "2 reviews"). Chinese has no plural inflection, so both
// forms carry the same wording — only the measure word differs where it reads better.
const COUNT_KEYS: Record<string, [string, string]> = {
  review: ["{{count}} review", "{{count}} reviews"],
  blocked: ["{{count}} blocked", "{{count}} blockeds"],
  canceled: ["{{count}} canceled", "{{count}} canceleds"],
  move: ["{{count}} move", "{{count}} moves"],
  filing: ["{{count}} filing", "{{count}} filings"],
  claim: ["{{count}} claim", "{{count}} claims"],
  assignment: ["{{count}} assignment", "{{count}} assignments"],
  comment: ["{{count}} comment", "{{count}} comments"],
  "chat message": ["{{count}} chat message", "{{count}} chat messages"],
};

function summarize(rows: BoardWakeRow[]): { text: string; attention: boolean } {
  const counts: Record<string, number> = {};
  const bump = (key: string) => (counts[key] = (counts[key] || 0) + 1);
  for (const row of rows) {
    if (row.kind === "moved" && row.to === "review") bump("review");
    else if (row.kind === "moved" && row.to === "blocked") bump("blocked");
    else if (row.kind === "moved" && row.to === "canceled") bump("canceled");
    else if (row.kind === "moved") bump("move");
    else if (row.kind === "filed") bump("filing");
    else if (row.kind === "claimed") bump("claim");
    else if (row.kind === "assigned") bump("assignment");
    else if (row.kind === "comment") bump("comment");
    else if (row.kind === "chat") bump("chat message");
  }
  const parts = Object.entries(counts).map(([label, n]) => {
    const [one, many] = COUNT_KEYS[label];
    return i18n.t(n === 1 ? one : many, { count: n });
  });
  // reviews/blocked demand a decision — those tint the collapsed line amber
  const attention = (counts.review || 0) + (counts.blocked || 0) > 0;
  return { text: parts.join(", ") || i18n.t("update"), attention };
}

function rowText(row: BoardWakeRow): string {
  const item = row.item != null ? `#${row.item}` : "";
  const title = row.title ? ` ${row.title}` : "";
  switch (row.kind) {
    case "moved":
      return i18n.t("{{item}}{{title}} → {{to}} by {{actor}}", {
        item,
        title,
        // row.to is the store's raw state id, and English has always shown it verbatim
        // ("→ review by webb"). So the id ITSELF is the catalog key: English falls back to
        // the key and stays byte-identical, Chinese gets a word. Mapping through the
        // capitalised STATE_LABEL table instead would have turned English into
        // "→ In review by webb" — e2e/team.spec.ts catches exactly that.
        to: row.to ? i18n.t(row.to) : row.to,
        actor: row.actor,
      });
    case "filed":
      return i18n.t("{{actor}} filed {{item}}{{title}}", { actor: row.actor, item, title });
    case "claimed":
      return i18n.t("{{actor}} claimed {{item}}{{title}}", { actor: row.actor, item, title });
    case "assigned":
      return i18n.t("{{item}}{{title}} assigned to you", { item, title });
    case "comment":
      return i18n.t("{{actor}} commented on {{item}}{{title}}", { actor: row.actor, item, title });
    case "chat":
      return i18n.t("# team chat — {{actor}}", { actor: row.actor });
    default:
      return `${item}${title}`;
  }
}

function stateDot(row: BoardWakeRow): string {
  if (row.kind === "moved" && row.to === "review") return "board-dot review";
  if (row.kind === "moved" && row.to === "blocked") return "board-dot blocked";
  if (row.kind === "moved" && row.to === "done") return "board-dot done";
  if (row.kind === "claimed" || row.kind === "assigned") return "board-dot work";
  return "board-dot idle";
}

export function BoardWakeCard({ source }: { source: MessageSource }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [openNotes, setOpenNotes] = useState<Record<number, boolean>>({});
  const rows = source.board?.rows || [];
  const { text, attention } = summarize(rows);
  return (
    <div
      className={"boardwake" + (attention ? " attention" : "")}
      data-testid="boardwake-card"
    >
      <button
        className="boardwake-head"
        data-testid="boardwake-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <Icon name="table" size={14} />
        <span className="boardwake-title">{t("Board wake")}</span>
        <span className="boardwake-summary">{text}</span>
        <span className="spacer" />
        <span className={"boardwake-chevron" + (open ? " open" : "")}>
          <Icon name="chevronDown" size={13} />
        </span>
      </button>
      {open && (
        <div className="boardwake-body" data-testid="boardwake-body">
          {rows.map((row, i) => (
            <div className="boardwake-row" key={i}>
              <span className={stateDot(row)} />
              <span className="boardwake-row-main">
                <span className="boardwake-row-text">{rowText(row)}</span>
                {row.note &&
                  (openNotes[i] ? (
                    <span className="boardwake-note">{row.note}</span>
                  ) : (
                    <button
                      className="boardwake-note-toggle"
                      onClick={() => setOpenNotes((s) => ({ ...s, [i]: true }))}
                    >
                      {row.kind === "chat" || row.kind === "comment"
                        ? t("show message")
                        : t("show hand-off")}
                    </button>
                  ))}
              </span>
            </div>
          ))}
          {rows.length === 0 && (
            <div className="boardwake-note">{source.text}</div>
          )}
        </div>
      )}
    </div>
  );
}
