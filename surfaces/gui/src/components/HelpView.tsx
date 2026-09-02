import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { HELP_CHAPTERS, helpChapter, type HelpAction } from "../help";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";
import { Markdown } from "./Markdown";

// The in-app user manual (owner ask 2026-08-31). Same page shell as Settings/Connectors:
// a left sub-nav plus a centered panel. Two states — the overview (a card grid that IS the
// navigation) and a chapter (Markdown body with a "take me there" button on top).
//
// Every jump out of here goes through onNavigate, which App maps onto the deep-link helpers
// it already owns (openSettings / setSurface / startTour). This component knows nothing
// about surfaces, which keeps the manual testable on its own.

export function HelpView({
  initialChapter,
  onNavigate,
}: {
  initialChapter?: string;
  onNavigate: (action: HelpAction) => void;
}) {
  const { t } = useTranslation();
  const [openKey, setOpenKey] = useState<string | null>(initialChapter ?? null);
  const scroller = useRef<HTMLDivElement | null>(null);

  // An `app:help/<key>` link fired from inside a body lands here as a chapter swap; jump
  // back to the top so the reader isn't dropped mid-page of the new chapter.
  const go = (key: string | null) => {
    setOpenKey(key);
    scroller.current?.scrollTo?.({ top: 0 });
  };

  // A deep-link from elsewhere (another chapter's link while this view is already open)
  // must win over local state.
  useEffect(() => {
    if (initialChapter) setOpenKey(initialChapter);
  }, [initialChapter]);

  const chapter = openKey ? helpChapter(openKey) : undefined;

  const navItem = (key: string | null, icon: Parameters<typeof Icon>[0]["name"], label: string) => {
    const active = openKey === key;
    return (
      <button
        key={key ?? "overview"}
        className={
          "w-full text-left px-2.5 py-2 rounded-lg text-[13px] flex items-center gap-2 " +
          (active ? "bg-paper text-accent font-medium" : "text-muted hover:bg-paper hover:text-ink")
        }
        data-testid={key ? `help-nav-${key}` : "help-nav-overview"}
        onClick={() => go(key)}
      >
        <Icon name={icon} size={15} />
        <span className="truncate">{label}</span>
      </button>
    );
  };

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <nav className="page-subnav w-[208px] shrink-0 border-r border-line bg-panel/40 px-3 py-4 overflow-y-auto hairline-scroll">
        <div className="px-2 text-[13.5px] font-semibold mb-3 flex items-center gap-2">
          <Icon name="file" size={16} /> {t("Help")}
        </div>
        {navItem(null, "sparkle", t("Overview"))}
        <div className="h-px bg-line my-1.5 mx-2" />
        {HELP_CHAPTERS.map((c) => navItem(c.key, c.icon, t(c.title)))}
      </nav>

      <div ref={scroller} className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-3xl mx-auto px-7 py-6">
          {chapter ? (
            <section data-testid={`help-chapter-${chapter.key}`}>
              <PanelHead title={t(chapter.title)} sub={t(chapter.blurb)} />
              {chapter.goto && (
                <button
                  className="mb-5 text-[12.5px] px-3 py-2 rounded-lg border border-line bg-panel hover:border-lineStrong inline-flex items-center gap-1.5"
                  data-testid="help-goto"
                  onClick={() => onNavigate(chapter.goto!.action)}
                >
                  {t(chapter.goto.label)}
                  <Icon name="chevronRight" size={13} />
                </button>
              )}
              <div className="help-body">
                <Markdown text={chapter.body} />
              </div>
            </section>
          ) : (
            <section data-testid="help-overview">
              <PanelHead
                title={t("Help")}
                sub={t("How to get real work out of it — and how not to spend more than you need to.")}
              />
              <div className="help-creed">
                <ol>
                  <li>{t("Start on a free model — the AMD line or a local one.")}</li>
                  <li>{t("Switch to a paid model only when the job needs real thinking.")}</li>
                  <li>{t("Finish a job, then start a new session — old context is re-sent every turn.")}</li>
                </ol>
              </div>
              <div className="help-grid">
                {HELP_CHAPTERS.map((c) => (
                  <button
                    key={c.key}
                    className="help-card"
                    data-testid={`help-card-${c.key}`}
                    onClick={() => go(c.key)}
                  >
                    <span className="help-card-ico">
                      <Icon name={c.icon} size={16} />
                    </span>
                    <span className="help-card-title">{t(c.title)}</span>
                    <span className="help-card-blurb">{t(c.blurb)}</span>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </main>
  );
}
