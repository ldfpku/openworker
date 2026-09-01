import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getConnectors, getSessionConnections } from "../api";
import type { Attachment } from "../types";
import { ConnectorIcon } from "../connectors/ConnectorIcon";
import { indexConnectors, visualFor, type ConnectorMap } from "../connectors/visuals";
import { useRoots } from "../useRoots";
import { AddFolderForm } from "./AddFolderForm";

// Empty-state for a fresh Cowork session (§27): a greeting, exactly three concrete template
// tasks aimed at a manufacturing-floor audience (equipment/process/scheduling/quality/supply
// roles, not developers), and the composer — nothing else. No icon tiles (the title is the row);
// sub-line copy is always the task's OUTCOME, never connection state.
//
// Two mechanisms, three cards:
//  - Folder-driven (cards 1 & 2): no connector involved. A shared folder already on the session
//    → prefill straight away; otherwise the inline AddFolderForm opens first and the prefill
//    fires once the folder's added. Both cards route through the same `pickFolder` helper, which
//    remembers which card's prompt to fire via `pendingPrompt`.
//  - Connector-gated (card 3): dots on the sub-line (brand color = connected and enabled for this
//    session, grayscale = not — §23's vocabulary). Ready → "Start →" on hover, click prefills the
//    composer. Not ready → "Configure ›" always visible (for a gated row the setup action IS the
//    row's meaning), opening the §23 Session settings drawer — no second setup surface here.

// These prompts prefill the user's composer — visible to the user, so localized.
const FOLDER_PROMPT_KEY = "intro.folder_prompt";
const DOWNTIME_PROMPT_KEY = "intro.downtime_prompt";
const WEEKLY_PROMPT_KEY = "intro.weekly_prompt";

export function SessionIntro({
  sessionId,
  onOpenSessionSettings,
  onPrefill,
}: {
  sessionId: string;
  // Opens the §23 Session settings drawer (sources section) — the gated rows' Configure target.
  onOpenSessionSettings: () => void;
  onPrefill: (text: string, attachments?: Attachment[]) => void;
}) {
  const { t } = useTranslation();
  const { roots, busy, error, addRoot } = useRoots(sessionId);
  const [live, setLive] = useState<Set<string>>(new Set());
  const [byName, setByName] = useState<ConnectorMap>({});
  // Which card's prompt to prefill once the AddFolderForm succeeds (card 1 or card 2 — they
  // share this one mechanism); null when the form isn't open.
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);

  useEffect(() => {
    // Live = what this session can touch right now (connected AND not muted here) — the same
    // truth the §23 glance renders, so the dots here can never disagree with the row above.
    getSessionConnections(sessionId)
      .then((c) => setLive(new Set(c.connected.filter((x) => x.enabled).map((x) => x.connector))))
      .catch(() => {});
    getConnectors()
      .then((list) => setByName(indexConnectors(list)))
      .catch(() => {});
  }, [sessionId]);

  const shared = roots.filter((r) => !r.primary);
  const weixinReady = live.has("weixin");

  const dot = (name: string, on: boolean) => (
    <span className={"task-dot" + (on ? "" : " off")} key={name}>
      <ConnectorIcon connector={visualFor(name, "connector", byName)} size={12} />
    </span>
  );

  const pickFolder = (promptKey: string) => {
    // A shared folder already exists → straight to the prompt; otherwise share one first.
    if (shared.length > 0) onPrefill(t(promptKey));
    else setPendingPrompt(promptKey);
  };

  return (
    <div className="intro">
      <h1 className="greeting">
        <span className="mark">✦</span> {t("intro.greeting")}
      </h1>
      <p className="intro-lede">{t("intro.lede")}</p>

      <div className="intro-tasks">
        <button
          className="task-card"
          data-testid="intro-task-folder"
          onClick={() => pickFolder(FOLDER_PROMPT_KEY)}
        >
          <span className="task-card-body">
            <span className="task-card-title">{t("intro.task_folder_title")}</span>
            <span className="task-card-sub">{t("intro.task_folder_sub")}</span>
          </span>
          <span className="task-card-act">{t("intro.task_folder_cta")}</span>
        </button>
        {pendingPrompt && (
          <div className="intro-addfolder">
            <AddFolderForm
              startOpen
              busy={busy}
              onAdd={async (path, writable) => {
                const ok = await addRoot(path, writable);
                if (ok !== false) onPrefill(t(pendingPrompt));
                return ok;
              }}
              onDismiss={() => setPendingPrompt(null)}
            />
            {error && <div className="roots-err">{error}</div>}
          </div>
        )}

        <button
          className="task-card"
          data-testid="intro-task-downtime"
          onClick={() => pickFolder(DOWNTIME_PROMPT_KEY)}
        >
          <span className="task-card-body">
            <span className="task-card-title">{t("intro.task_downtime_title")}</span>
            <span className="task-card-sub">{t("intro.task_downtime_sub")}</span>
          </span>
          <span className="task-card-act">{t("intro.task_folder_cta")}</span>
        </button>

        <button
          className={"task-card" + (weixinReady ? "" : " gated")}
          data-testid="intro-task-weekly"
          onClick={() => (weixinReady ? onPrefill(t(WEEKLY_PROMPT_KEY)) : onOpenSessionSettings())}
        >
          <span className="task-card-body">
            <span className="task-card-title">{t("intro.task_weekly_title")}</span>
            <span className="task-card-sub">
              {dot("weixin", weixinReady)}
              {t("intro.task_weekly_sub")}
            </span>
          </span>
          <span className="task-card-act">
            {weixinReady ? t("intro.cta_start") : t("intro.cta_configure")}
          </span>
        </button>
      </div>
    </div>
  );
}
