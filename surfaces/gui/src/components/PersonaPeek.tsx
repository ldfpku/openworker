import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getPersonaDetail, type PersonaDetail } from "../api";
import { fullPersonaName } from "../personaScope";
import { isComposing } from "../ime";
import { BTN_ACCENT_SM, BTN_BORDERED_SM } from "./buttons";
import { CopyButton } from "./CopyButton";
import { IconButton } from "./IconButton";
import { Markdown } from "./Markdown";

// A read-only look at the coworker about to run (or running) a session: its identity, what
// it may touch, and — the part nobody could see before — the actual instructions it works
// from. Opened from the composer's coworker picker ("View") and from the session subtitle.
// Owner ask 2026-09-10: "after picking a coworker there was no way to read what it is".
// Management (enable, default, export, delete) stays on the Settings detail page; this is
// a glance, so one button leads there and nothing here mutates anything.

const SEC_H = "text-[11px] uppercase tracking-[0.05em] text-faint font-semibold";

// A manifest's default_permission_mode as the composer names it (its Mode menu is where
// people know these words from); an unknown value falls back to the raw id.
const MODE_KEY: Record<string, string> = {
  interactive: "composer.mode.interactive",
  discuss: "composer.mode.discuss",
  plan: "composer.mode.plan",
  auto: "composer.mode.auto",
  "bypass-approvals": "composer.mode.auto",
  "auto-approve": "composer.mode.auto_approve",
};
export function permissionModeLabel(t: (key: string) => string, mode: string): string {
  const key = MODE_KEY[mode];
  return key ? t(key) : mode;
}

export function PersonaPrompt({
  prompt,
  testId = "persona-prompt",
}: {
  prompt: string;
  testId?: string;
}) {
  const { t } = useTranslation();
  // Rendered markdown reads better for the prose most prompts are; the raw view is the
  // exact bytes the model receives — useful when a heading or a list looks off.
  const [raw, setRaw] = useState(false);
  return (
    <div data-testid={testId}>
      <div className="flex items-center gap-2 mb-1.5">
        <span className={SEC_H}>{t("persona.prompt_label")}</span>
        <span className="text-[11px] text-faint">
          {t("persona.prompt_chars", { count: prompt.length })}
        </span>
        <span className="flex-1" />
        <button
          className="text-[11.5px] text-muted hover:text-ink"
          onClick={() => setRaw((v) => !v)}
          data-testid={`${testId}-toggle`}
        >
          {raw ? t("persona.prompt_rendered") : t("persona.prompt_raw")}
        </button>
        <CopyButton text={prompt} />
      </div>
      {raw ? (
        <pre className="text-[12px] leading-relaxed whitespace-pre-wrap break-words bg-paper rounded-lg border border-line px-3.5 py-3 font-mono text-ink max-h-[52vh] overflow-y-auto hairline-scroll">
          {prompt}
        </pre>
      ) : (
        <div className="text-[13px] bg-paper rounded-lg border border-line px-3.5 py-1 max-h-[52vh] overflow-y-auto hairline-scroll">
          <Markdown text={prompt} />
        </div>
      )}
    </div>
  );
}

export function PersonaPeek({
  personaId,
  onClose,
  onManage,
}: {
  personaId: string;
  onClose: () => void;
  // Opens Settings ▸ Coworkers ▸ this coworker (the management page).
  onManage?: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<PersonaDetail | null | undefined>(undefined);

  useEffect(() => {
    let live = true;
    setDetail(undefined);
    getPersonaDetail(personaId)
      .then((d) => live && setDetail(d && (d as { id?: string }).id ? d : null))
      .catch(() => live && setDetail(null));
    return () => {
      live = false;
    };
  }, [personaId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !isComposing(e)) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // The general coworker reads as it does in the picker ("OpenWorker (general)"), not
  // as the family word — a modal titled "Coworker" says nothing about which one.
  const name = detail
    ? detail.id === "cowork"
      ? t("setup.general_coworker")
      : fullPersonaName(detail.name, detail.id)
    : personaId;

  return (
    <div className="fixed inset-0 z-50" data-testid="persona-peek">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[1px]" onClick={onClose} />
      <div className="absolute left-1/2 top-[6vh] -translate-x-1/2 w-[680px] max-w-[94vw] max-h-[88vh] rounded-xl2 border border-line bg-panel shadow-2xl overflow-hidden flex flex-col">
        <div className="px-5 pt-4 pb-3 border-b border-line flex items-center gap-3 shrink-0">
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-semibold truncate" data-testid="persona-peek-name">
              {name}
            </div>
            {detail?.tagline && <div className="text-[12px] text-muted">{t(detail.tagline)}</div>}
          </div>
          {onManage && detail && (
            <button
              className={BTN_BORDERED_SM}
              onClick={() => onManage(detail.id)}
              data-testid="persona-peek-manage"
            >
              {t("persona.peek_manage")}
            </button>
          )}
          <IconButton icon="x" onClick={onClose} label={t("Close")} data-testid="persona-peek-close" />
        </div>
        <div className="p-5 overflow-y-auto hairline-scroll flex-1">
          {detail === undefined ? (
            <div className="text-[12.5px] text-muted">{t("persona.loading")}</div>
          ) : detail === null ? (
            <div className="text-[12.5px] text-danger">{t("persona.load_error")}</div>
          ) : (
            <>
              {detail.description && (
                <div className="text-[13px] text-ink mb-4" data-testid="persona-peek-about">
                  <Markdown text={t(detail.description)} />
                </div>
              )}
              <div className="flex flex-wrap gap-x-5 gap-y-2 text-[12px] text-muted mb-4">
                <span>
                  <span className={SEC_H + " mr-1.5"}>{t("persona.tool_calls")}</span>
                  {detail.tools.length ? detail.tools.join(" · ") : "—"}
                </span>
                <span>
                  <span className={SEC_H + " mr-1.5"}>{t("persona.default_mode_label")}</span>
                  {permissionModeLabel(t, detail.default_permission_mode)}
                </span>
                {detail.requires_folder && (
                  <span>
                    <span className={SEC_H + " mr-1.5"}>{t("persona.workspace_label")}</span>
                    {t("persona.workspace_picked")}
                  </span>
                )}
              </div>
              {detail.system_prompt ? (
                <PersonaPrompt prompt={detail.system_prompt} testId="persona-peek-prompt" />
              ) : (
                <div className="text-[12.5px] text-faint">{t("persona.prompt_empty")}</div>
              )}
              {detail.source && (
                <div className="text-[11px] text-faint mt-3 truncate" title={detail.source}>
                  {t("persona.prompt_source", { path: detail.source })}
                </div>
              )}
              <div className="flex items-center gap-2 mt-4">
                <button className={BTN_ACCENT_SM} onClick={onClose} data-testid="persona-peek-done">
                  {t("Close")}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
