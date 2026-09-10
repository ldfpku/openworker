// The Expert Library: browse/search over the bundled expert-prompt pack (zh + en) and the
// Skills pack (LIBRARY-SPEC P1), plus turning what you find into something the app actually
// runs (P2). Two content tabs share one search box and one category-chip row; each card opens
// a detail modal that lazy-fetches (and caches) the full prompt / SKILL.md text, with a
// one-click copy. An expert's "Start session" installs it as a persona (consent modal, same
// trust language as Settings ▸ Coworkers), enables it, and opens a session bound to it; a
// skill's detail modal installs it into the global skills directory the same way SkillsTab does.
//
// P4 (owner ask 2026-09-10): the library is also EDITABLE, on this machine only. Any expert
// can be edited in place (a local override — the pack's own file is never touched, and
// "Restore original" drops the override), and new experts can be written from scratch
// ("New expert"). Both live in the app's state dir, so an app update never overwrites them;
// an expert already installed as a coworker is re-installed from the saved text. Installed
// skills get the same treatment through the skill page: edit the local copy's SKILL.md,
// open its folder for the scripts, or put the shipped original back.

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import i18n from "../i18n";
import { Markdown } from "./Markdown";
import {
  libraryActivateExpert,
  libraryDeleteExpert,
  libraryExperts,
  libraryExpertPrompt,
  libraryInstallExpert,
  libraryInstallSkills,
  libraryOverview,
  librarySaveExpert,
  librarySkillDetail,
  librarySkills,
  libraryStatus,
  listSkills,
  revealSkill,
  updateSkill,
  type LibraryExpert,
  type LibraryExpertPrompt,
  type LibraryExpertVariant,
  type LibrarySkill,
  type PersonaConsent,
  type SkillRow,
} from "../api";
import { isComposing } from "../ime";
import { RISK_PHRASE } from "./PersonasTab";
import { BTN_ACCENT, BTN_BORDERED, BTN_BORDERED_SM, BTN_DANGER_SM, BTN_OUTLINE_SM } from "./buttons";
import { IconButton } from "./IconButton";

const CARD = "rounded-xl border border-line bg-panel/60";
const CARD_SELECTED = "rounded-xl border border-accent bg-panel/60";
const CHIP = "text-[10.5px] px-1.5 py-0.5 rounded border border-line text-muted shrink-0";
const PILL_ON = BTN_OUTLINE_SM + " bg-accentSoft";
const PILL_OFF = BTN_BORDERED_SM;

// Expert-team multi-select (LIBRARY-SPEC P3): a pick-6 cap on how many experts one
// "build a team" pass can install teammate variants for in one go.
const MAX_TEAM_SIZE = 6;

type Tab = "experts" | "skills";
type PromptResult = LibraryExpertPrompt;
type SkillResult = {
  name: string;
  description: string;
  description_zh?: string;
  skill_md: string;
  skill_md_zh?: string;
  files: string[];
};

// 技能库的中文层：数据里带 description_zh / skill_md_zh 时中文界面优先展示，
// 缺译文或英文界面回退英文原文（译文中链接、代码本就保留原样）。
const zhUI = () => (i18n.language || "").toLowerCase().startsWith("zh");
const skillDesc = (s: { description: string; description_zh?: string }) =>
  zhUI() && s.description_zh ? s.description_zh : s.description;

type Detail =
  | { kind: "expert"; id: string; lib: "zh" | "en"; pair: boolean; categoryName: string }
  | { kind: "skill"; name: string; categoryName: string; scripts: number; compatibility?: string };

// The expert editor (P4): create a new local expert, or edit one in place. Editing a pack
// expert writes an override under the same id; its category stays the pack's.
type ExpertEditor =
  | { mode: "create"; lib: "zh" | "en" }
  | { mode: "edit"; lib: "zh" | "en"; id: string; local: boolean };

// The exact input class the Skills settings editor uses, so the two editors read as one.
const INPUT =
  "w-full px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";

// The library unmounts whenever another surface shows (Settings, a session…). Its browse
// state — which tab/language, the search, the category chip — lives here so coming back
// lands where the person left off instead of on Experts/中文 with an empty search
// (audit 2026-09-10). Team picks are deliberately NOT kept: half a team from an earlier
// visit would be a surprise.
const BROWSE_DEFAULTS = { tab: "experts" as Tab, lib: "zh" as "zh" | "en", query: "", category: "all" };
const browseMemory: { tab: Tab; lib: "zh" | "en"; query: string; category: string } = { ...BROWSE_DEFAULTS };
/** Test hook: forget the remembered browse state between renders. */
export function resetLibraryBrowseMemory() {
  Object.assign(browseMemory, BROWSE_DEFAULTS);
}
const FIELD_LABEL = "text-[12px] text-muted";
const MAX_EDITOR_PROMPT = 200_000;

type LibraryStatus = {
  experts: Record<string, { solo?: LibraryExpertVariant; worker?: LibraryExpertVariant }>;
  skills: string[];
};

// One expert picked into a prospective team — a snapshot of just enough card data to
// install its "teammate" variant and show it back in the bar/modal without re-fetching.
type TeamMember = { lib: "zh" | "en"; id: string; name: string; categoryName: string };
const teamKey = (m: { lib: string; id: string }) => `${m.lib}:${m.id}`;

// Same plain-language capability line PersonasTab's ConsentCard renders (RISK_PHRASE,
// each translated, joined with a trailing "and") — shared here so the compact consent
// modal and the team-install aggregate view read identically.
function riskSummary(t: (key: string, opts?: Record<string, unknown>) => string, risk: string[]): string {
  const phrases = (risk.length ? risk : ["read"]).map((r) => t(RISK_PHRASE[r] || r));
  return phrases.join(", ").replace(/, ([^,]*)$/, `${t(" and ")}$1`);
}

// The install→consent→enable flow shared by the expert card's "Start session" button and
// the detail modal's "Install as coworker" button — same two API calls either way, they only
// differ in what happens once enabling succeeds (mode "start" opens a session; "installOnly"
// just leaves the button reading "Installed"). "error" only ever means the install call
// itself failed (no consent to show yet) — an enable failure instead lands back on "ready"
// with `error` set, so the consent details stay on screen alongside the message.
type ExpertFlow = {
  lib: "zh" | "en";
  id: string;
  categoryName: string;
  mode: "start" | "installOnly";
  status: "ready" | "activating" | "error";
  personaId?: string;
  consent?: PersonaConsent[];
  error?: string;
};

// Clipboard write, with a legacy execCommand fallback for contexts where the async API is
// unavailable or rejects (e.g. no trusted-gesture / permission in some webviews).
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the legacy path */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export function LibraryView({
  onStartExpertSession,
  onStartTeamSession,
  onOpenSkillsSettings,
}: {
  // Opens a NEW session bound to this persona (the same "browse a persona, start a
  // session for it" mechanism the sidebar's own New-session action uses) and switches
  // back to the conversation surface. Expert roles never gate on a folder.
  onStartExpertSession: (personaId: string) => void;
  // Multi-select "build an expert team" (P3): once every picked expert's "teammate"
  // variant is installed + enabled, hands off the free-text goal and the member names
  // so the caller can start an Expert Team Lead session and prefill its composer.
  onStartTeamSession: (goal: string, names: string) => void;
  // Settings ▸ Skills — where a skill is written from scratch (the editor lives there).
  onOpenSkillsSettings?: () => void;
}) {
  const { t } = useTranslation();
  const [overview, setOverview] = useState<{ ok: boolean } | null>(null);
  const [tab, setTab] = useState<Tab>(browseMemory.tab);
  const [lib, setLib] = useState<"zh" | "en">(browseMemory.lib);
  const [query, setQuery] = useState(browseMemory.query);
  const [category, setCategory] = useState<string>(browseMemory.category);
  useEffect(() => {
    Object.assign(browseMemory, { tab, lib, query, category });
  }, [tab, lib, query, category]);
  const [experts, setExperts] = useState<LibraryExpert[] | null>(null); // null = loading
  const [skills, setSkills] = useState<LibrarySkill[] | null>(null); // null = loading
  const [detail, setDetail] = useState<Detail | null>(null);
  const [status, setStatus] = useState<LibraryStatus | null>(null);
  const [expertFlow, setExpertFlow] = useState<ExpertFlow | null>(null);
  const [teamMode, setTeamMode] = useState(false);
  const [teamSelected, setTeamSelected] = useState<TeamMember[]>([]);
  const [teamLimitHit, setTeamLimitHit] = useState(false);
  const [teamModalOpen, setTeamModalOpen] = useState(false);
  // Bumped by the retry button — re-runs both load effects below.
  const [reloadTick, setReloadTick] = useState(0);
  // P4: the open expert editor, and the one-line confirmation after a save/restore/delete
  // (the list re-renders underneath it, so the change itself is visible too).
  const [editor, setEditor] = useState<ExpertEditor | null>(null);
  const [notice, setNotice] = useState<{ text: string; tone: "ok" | "warn" } | null>(null);
  const noticeTimer = useRef<number | null>(null);
  const showNotice = useCallback((text: string, tone: "ok" | "warn" = "ok") => {
    setNotice({ text, tone });
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 6000);
  }, []);
  useEffect(() => () => {
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
  }, []);

  const promptCache = useRef<Map<string, PromptResult>>(new Map());
  const skillCache = useRef<Map<string, SkillResult>>(new Map());

  const loadStatus = useCallback(() => {
    libraryStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    // reloadTick makes these effects re-runnable, so guard against a stale in-flight
    // response from before a retry landing after (and clobbering) the fresh one.
    let live = true;
    setOverview(null);
    setSkills(null);
    libraryOverview()
      .then((r) => live && setOverview({ ok: r.ok }))
      // A failed fetch is not the backend's "no pack on disk" verdict — leave the
      // overview unknown so the retryable load-failed path handles it, not packMissing.
      .catch(() => live && setOverview(null));
    librarySkills()
      .then((s) => live && setSkills(s))
      .catch(() => live && setSkills([]));
    loadStatus();
    return () => {
      live = false;
    };
  }, [loadStatus, reloadTick]);

  // Bumped after a save/restore/delete (P4): re-pulls the listing WITHOUT blanking the
  // grid — the person just edited one card and should see it change in place, not the
  // whole page flash "Loading…".
  const [expertsTick, setExpertsTick] = useState(0);
  const keepGridRef = useRef(false);
  useEffect(() => {
    let live = true;
    if (!keepGridRef.current) setExperts(null);
    keepGridRef.current = false;
    libraryExperts(lib)
      .then((e) => live && setExperts(e))
      .catch(() => live && setExperts([]));
    return () => {
      live = false;
    };
  }, [lib, reloadTick, expertsTick]);

  // Category chips are per-dataset — reset the filter whenever the dataset underneath
  // them changes so a stale selection never silently hides everything. Not on mount:
  // a remembered category must survive coming back to the page.
  const datasetKey = useRef(`${tab}:${lib}`);
  useEffect(() => {
    if (datasetKey.current === `${tab}:${lib}`) return;
    datasetKey.current = `${tab}:${lib}`;
    setCategory("all");
  }, [tab, lib]);

  // Stable identities (refs only, no reactive deps) — so an open detail modal's fetch effect
  // never re-fires just because the page behind it re-rendered (a search keystroke, etc.).
  const fetchPrompt = useCallback(async (l: "zh" | "en", id: string): Promise<PromptResult | null> => {
    const key = `${l}:${id}`;
    const cached = promptCache.current.get(key);
    if (cached) return cached;
    // A throw (sidecar restarting, non-JSON 500) reads as "could not load", never as a
    // modal stuck on "Loading…" (audit 2026-09-10).
    const r = await libraryExpertPrompt(l, id).catch(() => null);
    if (r) promptCache.current.set(key, r);
    return r;
  }, []);

  const fetchSkill = useCallback(async (name: string): Promise<SkillResult | null> => {
    const cached = skillCache.current.get(name);
    if (cached) return cached;
    const r = await librarySkillDetail(name).catch(() => null);
    if (r) skillCache.current.set(name, r);
    return r;
  }, []);

  // Step 1 of install→consent→enable: convert the library entry into an installed (but
  // disabled/unsurfaced) persona and open the compact consent modal on its result. The
  // caller (a card or the detail modal) awaits this to know when to drop its own busy state.
  const beginExpertFlow = useCallback(
    async (l: "zh" | "en", id: string, categoryName: string, mode: ExpertFlow["mode"]) => {
      const r = await libraryInstallExpert(l, id).catch(() => ({ ok: false as const, error: t("unreachable") }));
      if (!r.ok || !r.persona_id) {
        setExpertFlow({
          lib: l,
          id,
          categoryName,
          mode,
          status: "error",
          error: r.error || t("Could not install this coworker."),
        });
        return;
      }
      setExpertFlow({
        lib: l,
        id,
        categoryName,
        mode,
        status: "ready",
        personaId: r.persona_id,
        consent: r.consent || [],
      });
    },
    [t],
  );

  // Step 2: enable the installed persona. Success refreshes status and — for the "start"
  // mode only — hands off to the caller's session-start mechanism.
  const confirmExpertFlow = async () => {
    if (!expertFlow || expertFlow.status !== "ready" || !expertFlow.personaId) return;
    const { mode, personaId } = expertFlow;
    setExpertFlow((f) => (f ? { ...f, status: "activating", error: undefined } : f));
    const r = await libraryActivateExpert(personaId).catch(() => ({ ok: false as const, error: t("unreachable") }));
    if (!r.ok) {
      setExpertFlow((f) =>
        f ? { ...f, status: "ready", error: r.error || t("Could not enable this coworker.") } : f,
      );
      return;
    }
    loadStatus();
    setExpertFlow(null);
    if (mode === "start") onStartExpertSession(personaId);
  };

  const closeExpertFlow = () => setExpertFlow(null);

  const installSkill = async (name: string): Promise<{ ok: boolean; error?: string }> => {
    const r = await libraryInstallSkills([name]).catch(() => ({ ok: false as const, error: t("unreachable") }));
    if (!r.ok) return { ok: false, error: r.error };
    const item = (r.results || []).find((x) => x.name === name);
    if (item && !item.ok) return { ok: false, error: item.error };
    loadStatus();
    return { ok: true };
  };

  // P4: a save/restore/delete changed what the listing and the prompt say — drop the
  // cached prompt for that id and re-pull the listing + install status.
  const refreshAfterEdit = useCallback(
    (l: "zh" | "en", id?: string) => {
      if (id) promptCache.current.delete(`${l}:${id}`);
      else promptCache.current.clear();
      keepGridRef.current = true;
      setExpertsTick((n) => n + 1);
      loadStatus();
    },
    [loadStatus],
  );

  const unreachable = () => ({ ok: false as const, error: t("unreachable") });

  const restoreExpert = async (l: "zh" | "en", id: string) => {
    const r = await libraryDeleteExpert(l, id).catch(unreachable);
    if (!r.ok) {
      showNotice(r.error || t("Could not restore the original."), "warn");
      return false;
    }
    refreshAfterEdit(l, id);
    showNotice(
      r.reinstalled?.length
        ? t("Original restored — the installed coworker was updated too.")
        : t("Original restored."),
    );
    return true;
  };

  const deleteLocalExpert = async (l: "zh" | "en", id: string) => {
    const r = await libraryDeleteExpert(l, id).catch(unreachable);
    if (!r.ok) {
      showNotice(r.error || t("Could not delete this expert."), "warn");
      return false;
    }
    refreshAfterEdit(l, id);
    // A deleted expert leaves a half-built team: drop it from the picks (audit 2026-09-10).
    setTeamSelected((cur) => cur.filter((m) => teamKey(m) !== teamKey({ lib: l, id })));
    showNotice(
      r.uninstalled?.length
        ? t("Expert deleted from this machine, and its coworker was uninstalled.")
        : t("Expert deleted from this machine."),
    );
    return true;
  };

  // Entering clears any stale pick from a previous pass; leaving (the pill again, or the
  // team bar's own Cancel) drops the picks too — there's nowhere else they'd make sense.
  const toggleTeamMode = () =>
    setTeamMode((v) => {
      if (v) setTeamSelected([]);
      return !v;
    });

  const toggleTeamSelect = (m: TeamMember) =>
    setTeamSelected((cur) => {
      const exists = cur.some((x) => teamKey(x) === teamKey(m));
      if (exists) return cur.filter((x) => teamKey(x) !== teamKey(m));
      if (cur.length >= MAX_TEAM_SIZE) {
        setTeamLimitHit(true);
        window.setTimeout(() => setTeamLimitHit(false), 2000);
        return cur;
      }
      return [...cur, m];
    });

  const removeTeamMember = (key: string) =>
    setTeamSelected((cur) => cur.filter((x) => teamKey(x) !== key));

  const cancelTeamMode = () => {
    setTeamMode(false);
    setTeamSelected([]);
  };

  // Shared by the modal's own × / Escape / backdrop AND by a successful finish — either
  // way the multi-select session is over (LIBRARY-SPEC P3: "退出弹层/完成后清空多选模式").
  const closeTeamModal = () => {
    setTeamModalOpen(false);
    setTeamMode(false);
    setTeamSelected([]);
  };

  const handleTeamDone = (goal: string, names: string) => {
    loadStatus();
    closeTeamModal();
    onStartTeamSession(goal, names);
  };

  const q = query.trim().toLowerCase();
  const allExperts = experts ?? [];
  const expertCategories = Array.from(new Set(allExperts.map((e) => e.categoryName)));
  const filteredExperts = allExperts.filter(
    (e) =>
      (category === "all" || e.categoryName === category) &&
      (!q || `${e.name} ${e.description} ${e.categoryName}`.toLowerCase().includes(q)),
  );

  const allSkills = skills ?? [];
  const skillCategories = Array.from(new Set(allSkills.map((s) => s.categoryName)));
  const filteredSkills = allSkills.filter(
    (s) =>
      (category === "all" || s.categoryName === category) &&
      (!q || `${s.name} ${s.description} ${s.description_zh || ""} ${s.categoryName}`.toLowerCase().includes(q)),
  );

  const categories = tab === "experts" ? expertCategories : skillCategories;
  const loading = tab === "experts" ? experts === null : skills === null;
  // Only the backend's explicit verdict means the pack is absent from disk. An empty
  // list without that verdict is a load that fell over (fetch failed, sidecar still
  // warming up) — recoverable, so it gets a retry button instead of a dev-facing
  // "run gen_library.py" that an installed app's user can do nothing with.
  const packMissing = !loading && overview?.ok === false;
  const loadFailed =
    !loading &&
    !packMissing &&
    (tab === "experts" ? allExperts.length === 0 : allSkills.length === 0);
  const filteredCount = tab === "experts" ? filteredExperts.length : filteredSkills.length;

  return (
    <main className="flex-1 min-w-0 flex flex-col bg-paper">
      <div className="h-12 shrink-0 px-5 flex items-center gap-2 border-b border-line bg-paper">
        <span className="text-[13px] font-semibold">{t("Expert library")}</span>
        {!loading && !packMissing && !loadFailed && (
          <span className="text-[12px] text-faint">{t("{{count}} items", { count: filteredCount })}</span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto hairline-scroll">
        <div className="max-w-5xl mx-auto px-7 py-6">
          <div className="flex items-center gap-2 flex-wrap mb-4">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("Search experts (name / description / category)...")}
              className="flex-1 min-w-[220px] px-3 py-1.5 rounded-lg border border-line bg-paper text-[12.5px] text-ink outline-none focus:border-accent"
              data-testid="library-search"
            />
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                className={tab === "experts" ? PILL_ON : PILL_OFF}
                onClick={() => setTab("experts")}
                data-testid="library-tab-experts"
              >
                {t("Experts")}
              </button>
              <button
                className={tab === "skills" ? PILL_ON : PILL_OFF}
                onClick={() => setTab("skills")}
                data-testid="library-tab-skills"
              >
                {t("Skills")}
              </button>
            </div>
            {tab === "experts" && (
              <select
                value={lib}
                onChange={(e) => setLib(e.target.value as "zh" | "en")}
                className="text-[12px] px-2.5 py-1.5 rounded-lg border border-line bg-paper text-ink outline-none focus:border-accent shrink-0"
                data-testid="library-lib-select"
              >
                <option value="zh">{t("Chinese")}</option>
                <option value="en">{t("English")}</option>
              </select>
            )}
            {tab === "experts" && (
              <button
                className={teamMode ? PILL_ON : PILL_OFF}
                onClick={toggleTeamMode}
                data-testid="library-team-toggle"
              >
                {t("Build an expert team")}
              </button>
            )}
            {tab === "experts" && !teamMode && (
              <button
                className={BTN_ACCENT}
                onClick={() => setEditor({ mode: "create", lib })}
                data-testid="library-new-expert"
              >
                {t("New expert")}
              </button>
            )}
            {tab === "skills" && onOpenSkillsSettings && (
              <button
                className={BTN_BORDERED_SM}
                onClick={onOpenSkillsSettings}
                data-testid="library-new-skill"
                title={t("Skills are written in Settings ▸ Skills; installed library skills are edited there too.")}
              >
                {t("New skill…")}
              </button>
            )}
          </div>

          {notice && (
            <div
              className={
                "mb-3 text-[12.5px] rounded-lg border px-3 py-2 " +
                (notice.tone === "ok" ? "border-okLine bg-okSoft text-ink" : "border-warnInk/30 bg-warnSoft text-warnInk")
              }
              data-testid="library-notice"
            >
              {notice.text}
            </div>
          )}

          <div className="flex items-center gap-1.5 flex-wrap mb-5" data-testid="library-category-chips">
            <button className={category === "all" ? PILL_ON : PILL_OFF} onClick={() => setCategory("all")}>
              {t("All")}
            </button>
            {categories.map((c) => (
              <button
                key={c}
                className={category === c ? PILL_ON : PILL_OFF}
                onClick={() => setCategory(c)}
              >
                {c}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="text-[12.5px] text-muted py-10 text-center">{t("Loading…")}</div>
          ) : packMissing ? (
            // The backend re-checks the pack on every request, so this verdict can also
            // be a one-off read failure — offer the same retry rather than a dead end.
            <div className="text-[12.5px] text-muted py-10 text-center">
              <div>{t("Expert library pack missing — run packaging/gen_library.py to generate it first.")}</div>
              <button
                className={BTN_ACCENT + " mt-3"}
                onClick={() => setReloadTick((n) => n + 1)}
                data-testid="library-retry"
              >
                {t("Retry")}
              </button>
            </div>
          ) : loadFailed ? (
            <div className="text-[12.5px] text-muted py-10 text-center">
              <div>{t("Could not load the expert library.")}</div>
              <button
                className={BTN_ACCENT + " mt-3"}
                onClick={() => setReloadTick((n) => n + 1)}
                data-testid="library-retry"
              >
                {t("Retry")}
              </button>
            </div>
          ) : tab === "experts" ? (
            filteredExperts.length === 0 ? (
              <div className="text-[12.5px] text-muted py-10 text-center">
                {t("No experts match your search.")}
              </div>
            ) : (
              <div
                className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3"
                data-testid="library-expert-grid"
              >
                {filteredExperts.map((e) => (
                  <ExpertCard
                    key={e.id}
                    entry={e}
                    lib={lib}
                    variant={status?.experts[`${lib}:${e.id}`]?.solo}
                    onView={() =>
                      setDetail({ kind: "expert", id: e.id, lib, pair: e.pair, categoryName: e.categoryName })
                    }
                    onEdit={() => setEditor({ mode: "edit", lib, id: e.id, local: e.local === true })}
                    fetchPrompt={fetchPrompt}
                    onStartExpertSession={onStartExpertSession}
                    onInstallForStart={(l, id, categoryName) => beginExpertFlow(l, id, categoryName, "start")}
                    teamMode={teamMode}
                    teamSelected={teamSelected.some((m) => teamKey(m) === teamKey({ lib, id: e.id }))}
                    onToggleTeamSelect={() =>
                      toggleTeamSelect({ lib, id: e.id, name: e.name, categoryName: e.categoryName })
                    }
                  />
                ))}
              </div>
            )
          ) : filteredSkills.length === 0 ? (
            <div className="text-[12.5px] text-muted py-10 text-center">
              {t("No skills match your search.")}
            </div>
          ) : (
            <div
              className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3"
              data-testid="library-skill-grid"
            >
              {filteredSkills.map((s) => (
                <SkillCard
                  key={s.name}
                  entry={s}
                  installed={(status?.skills || []).includes(s.name)}
                  onView={() =>
                    setDetail({
                      kind: "skill",
                      name: s.name,
                      categoryName: s.categoryName,
                      scripts: s.scripts,
                      compatibility: s.compatibility,
                    })
                  }
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {detail?.kind === "expert" && (
        <ExpertDetailModal
          id={detail.id}
          initialLib={detail.lib}
          pair={detail.pair}
          categoryName={detail.categoryName}
          onClose={() => setDetail(null)}
          fetchPrompt={fetchPrompt}
          expertsStatus={status?.experts}
          onInstallAsCoworker={(l, id, categoryName) => beginExpertFlow(l, id, categoryName, "installOnly")}
          onEdit={(l, id, local) => {
            setDetail(null);
            setEditor({ mode: "edit", lib: l, id, local });
          }}
          onRestore={async (l, id) => {
            if (!window.confirm(t("Restore the shipped original? Your edits to this expert will be discarded."))) return;
            if (await restoreExpert(l, id)) setDetail(null);
          }}
          onDelete={async (l, id) => {
            if (!window.confirm(t("Delete this expert from this machine? This cannot be undone."))) return;
            if (await deleteLocalExpert(l, id)) setDetail(null);
          }}
        />
      )}
      {detail?.kind === "skill" && (
        <SkillDetailModal
          name={detail.name}
          categoryName={detail.categoryName}
          scripts={detail.scripts}
          compatibility={detail.compatibility}
          installed={(status?.skills || []).includes(detail.name)}
          onClose={() => setDetail(null)}
          fetchSkill={fetchSkill}
          onInstall={installSkill}
          onReinstall={async (name) => {
            const r = await libraryInstallSkills([name], true);
            const item = (r.results || []).find((x) => x.name === name);
            if (!r.ok || (item && !item.ok)) return { ok: false, error: r.error || item?.error };
            loadStatus();
            showNotice(t("Shipped original restored for {{name}}.", { name }));
            return { ok: true };
          }}
          onNotice={showNotice}
        />
      )}
      {editor && (
        <ExpertEditorModal
          editor={editor}
          categories={allExperts
            .filter((e) => !e.local)
            .map((e) => ({ category: e.category, categoryName: e.categoryName }))
            .filter((c, i, a) => a.findIndex((x) => x.category === c.category) === i)}
          fetchPrompt={fetchPrompt}
          onClose={() => setEditor(null)}
          onSaved={(res) => {
            setEditor(null);
            refreshAfterEdit(editor.lib, res.id);
            // A renamed expert keeps its place in a half-built team, under the new name.
            setTeamSelected((cur) =>
              cur.map((m) => (teamKey(m) === teamKey({ lib: editor.lib, id: res.id }) ? { ...m, name: res.name } : m)),
            );
            showNotice(
              res.created
                ? t("Expert saved on this machine.")
                : res.reinstalled?.length
                  ? t("Saved — the installed coworker runs on the new text from its next session.")
                  : t("Saved on this machine."),
            );
          }}
        />
      )}
      {/* Renders on top of a possibly-still-open detail modal (later in DOM = paints last),
          its own bumped z-index (z-[60] vs the detail modal's z-50) making that explicit
          rather than relying on paint order alone. */}
      {expertFlow && <ExpertConsentModal flow={expertFlow} onClose={closeExpertFlow} onConfirm={confirmExpertFlow} />}

      {teamMode && teamSelected.length > 0 && (
        <div
          className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 max-w-[92vw] rounded-xl2 border border-line bg-panel shadow-2xl px-4 py-3 flex items-center gap-3 flex-wrap"
          data-testid="library-team-bar"
        >
          <span className="text-[12.5px] text-ink shrink-0">
            {t("{{count}} experts selected", { count: teamSelected.length })}
          </span>
          <div className="flex items-center gap-1.5 flex-wrap">
            {teamSelected.map((m) => (
              <span key={teamKey(m)} className={CHIP + " flex items-center gap-1"}>
                {m.name}
                <IconButton
                  variant="inline"
                  icon="x"
                  size={12}
                  label={`${t("Remove")}: ${m.name}`}
                  onClick={() => removeTeamMember(teamKey(m))}
                />
              </span>
            ))}
          </div>
          {teamLimitHit && (
            <span className="text-[11.5px] text-danger shrink-0">
              {t("You can select up to {{max}} experts", { max: MAX_TEAM_SIZE })}
            </span>
          )}
          <button
            className={BTN_ACCENT}
            onClick={() => setTeamModalOpen(true)}
            data-testid="library-team-build"
          >
            {t("Build an expert team")}
          </button>
          <button className={BTN_BORDERED_SM} onClick={cancelTeamMode}>
            {t("Cancel")}
          </button>
        </div>
      )}

      {teamModalOpen && (
        <ExpertTeamModal
          members={teamSelected}
          expertsStatus={status?.experts}
          onClose={closeTeamModal}
          onDone={handleTeamDone}
        />
      )}
    </main>
  );
}

function ExpertCard({
  entry,
  lib,
  variant,
  onView,
  onEdit,
  fetchPrompt,
  onStartExpertSession,
  onInstallForStart,
  teamMode,
  teamSelected,
  onToggleTeamSelect,
}: {
  entry: LibraryExpert;
  lib: "zh" | "en";
  // The already-installed solo persona for this expert, if any (drives the "Installed"
  // chip and whether "Start session" can skip straight to a session).
  variant: LibraryExpertVariant | undefined;
  onView: () => void;
  // P4: open the editor on this expert (a pack expert gets a local override).
  onEdit: () => void;
  fetchPrompt: (lib: "zh" | "en", id: string) => Promise<PromptResult | null>;
  onStartExpertSession: (personaId: string) => void;
  onInstallForStart: (lib: "zh" | "en", id: string, categoryName: string) => Promise<void>;
  // "Build an expert team" multi-select (P3): while active, the card body itself toggles
  // selection (a checkbox replaces the "Installed" chip) and "Start session" hides — View
  // and Copy stay clickable, guarded with stopPropagation so they don't also toggle the pick.
  teamMode: boolean;
  teamSelected: boolean;
  onToggleTeamSelect: () => void;
}) {
  const { t } = useTranslation();
  const [copyState, setCopyState] = useState<"idle" | "busy" | "copied" | "error">("idle");
  const [startBusy, setStartBusy] = useState(false);

  const doCopy = async () => {
    setCopyState("busy");
    const r = await fetchPrompt(lib, entry.id);
    if (!r) {
      setCopyState("error");
      window.setTimeout(() => setCopyState("idle"), 1500);
      return;
    }
    const ok = await copyText(r.prompt);
    setCopyState(ok ? "copied" : "error");
    window.setTimeout(() => setCopyState("idle"), 1500);
  };

  const handleStart = async () => {
    if (variant?.enabled) {
      onStartExpertSession(variant.persona_id);
      return;
    }
    setStartBusy(true);
    try {
      await onInstallForStart(lib, entry.id, entry.categoryName);
    } finally {
      setStartBusy(false);
    }
  };

  const installed = variant?.enabled === true;

  return (
    <div
      className={
        (teamMode && teamSelected ? CARD_SELECTED : CARD) +
        " p-3.5 flex flex-col" +
        // In team mode the whole card is the hit target, so it has to LOOK like one.
        // Without a hover response the only hint that 276 cards are selectable was a
        // 1px hairline box in the corner (owner-hit 2026-08-31).
        (teamMode
          ? " cursor-pointer hover:border-lineStrong focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          : "")
      }
      data-testid={`expert-card-${entry.id}`}
      onClick={teamMode ? onToggleTeamSelect : undefined}
      // The card is the control, not the little box — so the role and the state live
      // here, where the click actually lands, and the box stays decorative.
      role={teamMode ? "checkbox" : undefined}
      aria-checked={teamMode ? teamSelected : undefined}
      aria-label={teamMode ? entry.name : undefined}
      tabIndex={teamMode ? 0 : undefined}
      onKeyDown={
        teamMode
          ? (event) => {
              if (event.key === " " || event.key === "Enter") {
                event.preventDefault();
                onToggleTeamSelect?.();
              }
            }
          : undefined
      }
    >
      <div className="flex items-start gap-2.5 mb-2">
        <div
          className="w-8 h-8 rounded-lg shrink-0 grid place-items-center text-[16px]"
          style={{ background: entry.color }}
          aria-hidden
        >
          {entry.emoji}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[10.5px] text-accent font-medium mb-0.5 truncate">{entry.categoryName}</div>
          <div className="text-[13.5px] font-semibold leading-snug">{entry.name}</div>
        </div>
        {teamMode ? (
          // Unchecked used to be a 1px `--line` (#e8eaed) hairline with no fill, on a
          // near-white card — invisible in practice, so the one control that says "you
          // may pick this" read as a rendering artifact. Now it is a real unchecked
          // checkbox: 2px `--line-strong` border over `--paper`, sized a touch larger.
          // The ✓ stays transparent when unchecked (it holds the box's size; showing a
          // faint one would read as "checked, but disabled").
          <span
            className={
              "w-[18px] h-[18px] rounded border-2 shrink-0 grid place-items-center " +
              "text-[11px] leading-none transition-colors " +
              (teamSelected
                ? "border-accent bg-accent text-white"
                : "border-lineStrong bg-paper text-transparent")
            }
            aria-hidden
            data-testid={`expert-team-check-${entry.id}`}
          >
            ✓
          </span>
        ) : (
          <span className="flex items-center gap-1 shrink-0">
            {/* Where the text comes from (P4): written here, or a pack expert edited here. */}
            {entry.local && (
              <span className={CHIP + " border-accent/40 text-accent"} data-testid={`expert-local-chip-${entry.id}`}>
                {t("This machine")}
              </span>
            )}
            {entry.modified && (
              <span className={CHIP + " border-accent/40 text-accent"} data-testid={`expert-modified-chip-${entry.id}`}>
                {t("Edited")}
              </span>
            )}
            {installed && (
              <span className={CHIP} data-testid={`expert-installed-chip-${entry.id}`}>
                {t("Installed")}
              </span>
            )}
          </span>
        )}
      </div>
      <div className="text-[12px] text-muted leading-relaxed line-clamp-3 flex-1 mb-3">
        {entry.description}
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        {!teamMode && (
          <button
            className={BTN_ACCENT}
            onClick={handleStart}
            disabled={startBusy}
            data-testid={`expert-start-${entry.id}`}
          >
            {startBusy ? t("Installing…") : t("Start session")}
          </button>
        )}
        <button className={BTN_BORDERED_SM} onClick={(e) => { e.stopPropagation(); onView(); }}>
          {t("View prompt")}
        </button>
        <button
          className={BTN_BORDERED_SM}
          onClick={(e) => { e.stopPropagation(); void doCopy(); }}
          disabled={copyState === "busy"}
        >
          {copyState === "copied" ? t("Copied") : copyState === "error" ? t("Copy failed") : t("Copy prompt")}
        </button>
        {!teamMode && (
          <IconButton
            icon="pencil"
            size={14}
            variant="bordered"
            small
            label={t("Edit prompt")}
            data-testid={`expert-edit-${entry.id}`}
            onClick={(e) => { e.stopPropagation(); onEdit(); }}
          />
        )}
      </div>
    </div>
  );
}

function SkillCard({
  entry,
  installed,
  onView,
}: {
  entry: LibrarySkill;
  installed: boolean;
  onView: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className={CARD + " p-3.5 flex flex-col"} data-testid={`skill-card-${entry.name}`}>
      <div className="flex items-start gap-2.5 mb-2">
        <div
          className="w-8 h-8 rounded-lg shrink-0 grid place-items-center text-[16px] bg-accentSoft text-accent"
          aria-hidden
        >
          🧪
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[10.5px] text-accent font-medium mb-0.5 truncate">{entry.categoryName}</div>
          <div className="text-[13.5px] font-semibold leading-snug">{entry.name}</div>
        </div>
        {installed && (
          <span className={CHIP} data-testid={`skill-installed-chip-${entry.name}`}>
            {t("Installed")}
          </span>
        )}
      </div>
      <div className="text-[12px] text-muted leading-relaxed line-clamp-3 flex-1 mb-3">
        {skillDesc(entry)}
      </div>
      <div className="flex items-center justify-between gap-2">
        <button className={BTN_BORDERED_SM} onClick={onView}>
          {t("View description")}
        </button>
        {entry.scripts > 0 && <span className={CHIP}>{t("{{count}} scripts", { count: entry.scripts })}</span>}
      </div>
    </div>
  );
}

function ModalShell({
  title,
  sub,
  onClose,
  headerExtra,
  children,
  testId = "library-detail-modal",
  panelClassName = "w-[640px]",
  z = "z-50",
}: {
  title: string;
  sub: string;
  onClose: () => void;
  headerExtra?: ReactNode;
  children: ReactNode;
  // The compact expert-consent modal (LIBRARY-SPEC P2) reuses this shell but needs its
  // own testid (so tests can tell it apart from the browse detail modal), a narrower
  // panel, and a higher z-index — it can open ON TOP of an already-open detail modal.
  testId?: string;
  panelClassName?: string;
  z?: string;
}) {
  const { t } = useTranslation();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // The Escape that cancels a pinyin candidate must not close (and discard) the modal.
      if (e.key === "Escape" && !isComposing(e)) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className={`fixed inset-0 ${z}`} data-testid={testId}>
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[1px]" onClick={onClose} />
      <div
        className={`absolute left-1/2 top-[6vh] -translate-x-1/2 ${panelClassName} max-w-[94vw] max-h-[88vh] rounded-xl2 border border-line bg-panel shadow-2xl overflow-hidden flex flex-col`}
      >
        <div className="px-5 pt-4 pb-3 border-b border-line flex items-center gap-3 shrink-0">
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-semibold truncate">{title}</div>
            <div className="text-[12px] text-muted">{sub}</div>
          </div>
          {headerExtra}
          <IconButton icon="x" onClick={onClose} label={t("Close")} data-testid={`${testId}-close`} />
        </div>
        <div className="p-5 overflow-y-auto hairline-scroll flex-1">{children}</div>
      </div>
    </div>
  );
}

function ExpertDetailModal({
  id,
  initialLib,
  pair,
  categoryName,
  onClose,
  fetchPrompt,
  expertsStatus,
  onInstallAsCoworker,
  onEdit,
  onRestore,
  onDelete,
}: {
  id: string;
  initialLib: "zh" | "en";
  pair: boolean;
  categoryName: string;
  onClose: () => void;
  fetchPrompt: (lib: "zh" | "en", id: string) => Promise<PromptResult | null>;
  expertsStatus: LibraryStatus["experts"] | undefined;
  onInstallAsCoworker: (lib: "zh" | "en", id: string, categoryName: string) => Promise<void>;
  // P4: edit in place / drop the local override / delete a local expert.
  onEdit: (lib: "zh" | "en", id: string, local: boolean) => void;
  onRestore: (lib: "zh" | "en", id: string) => void;
  onDelete: (lib: "zh" | "en", id: string) => void;
}) {
  const { t } = useTranslation();
  const [curLib, setCurLib] = useState<"zh" | "en">(initialLib);
  const [data, setData] = useState<PromptResult | null | undefined>(undefined); // undefined = loading
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const [installBusy, setInstallBusy] = useState(false);

  useEffect(() => {
    let live = true;
    setData(undefined);
    fetchPrompt(curLib, id).then((r) => live && setData(r));
    return () => {
      live = false;
    };
  }, [curLib, id, fetchPrompt]);

  const doCopy = async () => {
    if (!data) return;
    const ok = await copyText(data.prompt);
    setCopyState(ok ? "copied" : "error");
    window.setTimeout(() => setCopyState("idle"), 1500);
  };

  // The install/enable status tracks the language TAB currently in view — switching tabs
  // re-installs (and can re-enable) under that language's own pack id (persona_id rule:
  // "重装即换语言"), so each side of the toggle shows its own installed state.
  const installed = expertsStatus?.[`${curLib}:${id}`]?.solo?.enabled === true;

  const handleInstall = async () => {
    setInstallBusy(true);
    try {
      await onInstallAsCoworker(curLib, id, categoryName);
    } finally {
      setInstallBusy(false);
    }
  };

  return (
    <ModalShell
      title={data?.name || id}
      sub={categoryName}
      onClose={onClose}
      headerExtra={
        pair && (
          <button
            className={BTN_BORDERED_SM}
            onClick={() => setCurLib((l) => (l === "zh" ? "en" : "zh"))}
            data-testid="library-lang-toggle"
          >
            {curLib === "zh" ? t("View English original") : t("Back to Chinese")}
          </button>
        )
      }
    >
      {data === undefined ? (
        <div className="text-[12.5px] text-muted">{t("Loading…")}</div>
      ) : data === null ? (
        <div className="text-[12.5px] text-danger">{t("Could not load this prompt.")}</div>
      ) : (
        <>
          {(data.local || data.modified) && (
            <div className="text-[12px] text-muted mb-2" data-testid="expert-source-note">
              {data.local
                ? t("Written on this machine — the pack knows nothing of it.")
                : t("Edited on this machine — the shipped original is untouched and can be restored.")}
              {data.updated_at ? ` · ${new Date(data.updated_at).toLocaleString()}` : ""}
            </div>
          )}
          {/* Rendered markdown (the packs are authored in md); Copy still hands over the raw text. */}
          <div className="text-[13px] bg-paper rounded-lg border border-line px-3.5 py-1" data-testid="expert-prompt-md">
            <Markdown text={data.prompt} />
          </div>
          <div className="flex items-center gap-2 mt-3 flex-wrap">
            <button className={BTN_ACCENT} onClick={doCopy}>
              {copyState === "copied" ? t("Copied") : copyState === "error" ? t("Copy failed") : t("Copy")}
            </button>
            <button
              className={BTN_BORDERED_SM}
              onClick={() => onEdit(curLib, id, data.local === true)}
              data-testid="expert-detail-edit"
            >
              {t("Edit prompt")}
            </button>
            {installed ? (
              <button className={BTN_BORDERED_SM} disabled data-testid="expert-installed-badge">
                {t("Installed")}
              </button>
            ) : (
              <button
                className={BTN_BORDERED_SM}
                disabled={installBusy}
                onClick={handleInstall}
                data-testid="expert-install-as-coworker"
              >
                {installBusy ? t("Installing…") : t("Install as coworker")}
              </button>
            )}
            <span className="flex-1" />
            {data.modified && (
              <button className={BTN_DANGER_SM} onClick={() => onRestore(curLib, id)} data-testid="expert-restore">
                {t("Restore original")}
              </button>
            )}
            {data.local && (
              <button className={BTN_DANGER_SM} onClick={() => onDelete(curLib, id)} data-testid="expert-delete">
                {t("Delete")}
              </button>
            )}
          </div>
        </>
      )}
    </ModalShell>
  );
}

function SkillDetailModal({
  name,
  categoryName,
  scripts,
  compatibility,
  installed,
  onClose,
  fetchSkill,
  onInstall,
  onReinstall,
  onNotice,
}: {
  name: string;
  categoryName: string;
  scripts: number;
  compatibility?: string;
  installed: boolean;
  onClose: () => void;
  fetchSkill: (name: string) => Promise<SkillResult | null>;
  onInstall: (name: string) => Promise<{ ok: boolean; error?: string }>;
  // P4: put the shipped original back over an installed (edited) copy.
  onReinstall?: (name: string) => Promise<{ ok: boolean; error?: string }>;
  onNotice?: (text: string, tone?: "ok" | "warn") => void;
}) {
  const { t } = useTranslation();
  const [data, setData] = useState<SkillResult | null | undefined>(undefined); // undefined = loading
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  // "confirm" reveals the scripts/compatibility disclosure block (spec: no silent installs
  // of a skill that ships executable scripts) before the actual install call fires.
  const [installState, setInstallState] = useState<"idle" | "confirm" | "busy" | "error">("idle");
  const [installError, setInstallError] = useState("");
  // P4: the installed copy on this machine (Settings ▸ Skills' row for it) — what the
  // model actually loads. Editable here so a library skill can be tuned where it was found.
  const [localRow, setLocalRow] = useState<SkillRow | null | undefined>(undefined);
  const [localEditor, setLocalEditor] = useState<{ description: string; instructions: string } | null>(null);
  const [localBusy, setLocalBusy] = useState(false);
  const [localError, setLocalError] = useState("");
  const [localTick, setLocalTick] = useState(0);

  useEffect(() => {
    let live = true;
    setData(undefined);
    fetchSkill(name).then((r) => live && setData(r));
    return () => {
      live = false;
    };
  }, [name, fetchSkill]);

  useEffect(() => {
    if (!installed) {
      setLocalRow(null);
      setLocalEditor(null);
      return;
    }
    let live = true;
    setLocalRow(undefined);
    listSkills()
      .then((rows) => live && setLocalRow(rows.find((r) => r.name === name) || null))
      .catch(() => live && setLocalRow(null));
    return () => {
      live = false;
    };
  }, [installed, name, localTick]);

  const localDirty =
    !!localEditor &&
    !!localRow &&
    (localEditor.description !== localRow.description || localEditor.instructions !== localRow.instructions);
  // Esc / backdrop / × with unsaved edits to the local copy ask first (audit 2026-09-10).
  const close = () => {
    if (localDirty && !window.confirm(t("Discard your unsaved changes?"))) return;
    onClose();
  };

  const saveLocal = async () => {
    if (!localEditor) return;
    setLocalBusy(true);
    setLocalError("");
    try {
      const r = await updateSkill(name, {
        description: localEditor.description.trim(),
        instructions: localEditor.instructions,
      }).catch(() => ({ ok: false as const, error: t("unreachable") }));
      if (!r.ok) {
        setLocalError(r.error || t("Could not save the local copy."));
        return;
      }
      setLocalEditor(null);
      setLocalTick((n) => n + 1);
      onNotice?.(t("Local copy of {{name}} saved.", { name }));
    } finally {
      setLocalBusy(false);
    }
  };

  const reinstall = async () => {
    if (!onReinstall) return;
    if (!window.confirm(t("Put the shipped original back? Your edits to the local copy will be discarded."))) return;
    setLocalBusy(true);
    try {
      const r = await onReinstall(name).catch(() => ({ ok: false as const, error: t("unreachable") }));
      if (!r.ok) {
        setLocalError(r.error || t("Could not restore the original."));
        return;
      }
      setLocalEditor(null);
      setLocalTick((n) => n + 1);
    } finally {
      setLocalBusy(false);
    }
  };

  const reveal = async () => {
    const r = await revealSkill(name).catch(() => ({ ok: false as const, error: t("unreachable") }));
    if (!r.ok) setLocalError(r.error || t("Could not open the folder."));
  };

  // 展示与复制同源：中文界面且有译文时用 SKILL.zh.md，否则英文原文。
  const shownMd = data ? (zhUI() && data.skill_md_zh ? data.skill_md_zh : data.skill_md) : "";

  const doCopy = async () => {
    if (!data) return;
    const ok = await copyText(installed && localRow ? localRow.instructions : shownMd);
    setCopyState(ok ? "copied" : "error");
    window.setTimeout(() => setCopyState("idle"), 1500);
  };

  const doInstall = async () => {
    setInstallState("busy");
    const r = await onInstall(name).catch(() => ({ ok: false as const, error: t("unreachable") }));
    if (!r.ok) {
      setInstallError(r.error || t("Could not install this skill."));
      setInstallState("error");
      return;
    }
    setInstallState("idle"); // `installed` now flips true once the parent's status refetch lands
  };

  const files = data?.files ?? [];
  const shown = files.slice(0, 20);

  return (
    <ModalShell title={data?.name || name} sub={categoryName} onClose={close}>
      {data === undefined ? (
        <div className="text-[12.5px] text-muted">{t("Loading…")}</div>
      ) : data === null ? (
        <div className="text-[12.5px] text-danger">{t("Could not load this skill.")}</div>
      ) : (
        <>
          {data.description && (
            <div className="text-[12.5px] text-muted mb-3">{skillDesc(data)}</div>
          )}
          {/* Installed: the text shown is the local copy's — what the model actually loads
              (the shipped page could read differently after an edit, or in Chinese while
              the installed English copy is what runs; audit 2026-09-10). */}
          {installed && localRow && !localEditor && (
            <div className="text-[11.5px] text-faint mb-1.5" data-testid="skill-md-source">
              {t("Showing the installed copy on this machine — the text the model loads.")}
            </div>
          )}
          <div className="text-[13px] bg-paper rounded-lg border border-line px-3.5 py-1" data-testid="skill-md">
            <Markdown text={installed && localRow ? localRow.instructions : shownMd} />
          </div>
          <button className={BTN_ACCENT + " mt-3"} onClick={doCopy}>
            {copyState === "copied" ? t("Copied") : copyState === "error" ? t("Copy failed") : t("Copy")}
          </button>
          {files.length > 0 && (
            <div className="mt-4">
              <div className="text-[11px] uppercase tracking-[0.05em] text-faint font-semibold mb-2">
                {t("Files")}
              </div>
              <div className="space-y-1 font-mono text-[11.5px] text-muted">
                {shown.map((f) => (
                  <div key={f} className="truncate">
                    {f}
                  </div>
                ))}
              </div>
              <div className="text-[11.5px] text-faint mt-2">
                {t("{{count}} files total", { count: files.length })}
              </div>
            </div>
          )}
          {installed && (
            <div className="mt-4 rounded-lg border border-line bg-paper p-3.5" data-testid="skill-local-copy">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="text-[11px] uppercase tracking-[0.05em] text-faint font-semibold">
                  {t("Installed copy on this machine")}
                </div>
                <span className="flex-1" />
                {localRow && !localEditor && (
                  <>
                    <button
                      className={BTN_BORDERED_SM}
                      onClick={() =>
                        setLocalEditor({ description: localRow.description, instructions: localRow.instructions })
                      }
                      data-testid="skill-local-edit"
                    >
                      {t("Edit local copy")}
                    </button>
                    <button
                      className={BTN_BORDERED_SM}
                      onClick={() => void reveal()}
                      title={t("Scripts and other bundled files live in the skill's folder — edit them there.")}
                      data-testid="skill-local-reveal"
                    >
                      {t("Open folder")}
                    </button>
                    {onReinstall && (
                      <button
                        className={BTN_DANGER_SM}
                        onClick={() => void reinstall()}
                        disabled={localBusy}
                        data-testid="skill-local-reinstall"
                      >
                        {t("Restore original")}
                      </button>
                    )}
                  </>
                )}
              </div>
              {localRow === undefined ? (
                <div className="text-[12px] text-muted mt-2">{t("Loading…")}</div>
              ) : localRow === null ? (
                <div className="text-[12px] text-muted mt-2">{t("The installed copy could not be read.")}</div>
              ) : localEditor ? (
                <div className="mt-2.5">
                  <label className={FIELD_LABEL} htmlFor="skill-local-desc">
                    {t("Description")}
                  </label>
                  <input
                    id="skill-local-desc"
                    className={`${INPUT} mt-1 mb-3`}
                    value={localEditor.description}
                    onChange={(e) => setLocalEditor({ ...localEditor, description: e.target.value })}
                  />
                  <label className={FIELD_LABEL} htmlFor="skill-local-instructions">
                    {t("Instructions (SKILL.md body)")}
                  </label>
                  <textarea
                    id="skill-local-instructions"
                    className={`${INPUT} mt-1 mb-2 min-h-[220px] font-mono text-[12px]`}
                    value={localEditor.instructions}
                    spellCheck={false}
                    onChange={(e) => setLocalEditor({ ...localEditor, instructions: e.target.value })}
                    data-testid="skill-local-instructions"
                  />
                  <div className="text-[11.5px] text-faint mb-2.5">
                    {t("Scripts and other bundled files are not edited here — Open folder reaches them. Changes apply from the next session.")}
                  </div>
                  {localError && <div className="text-[12.5px] text-danger mb-2">{localError}</div>}
                  <div className="flex items-center gap-2">
                    <button
                      className={BTN_ACCENT}
                      disabled={localBusy || !localEditor.instructions.trim()}
                      onClick={() => void saveLocal()}
                      data-testid="skill-local-save"
                    >
                      {localBusy ? t("Saving…") : t("Save local copy")}
                    </button>
                    <button className={BTN_BORDERED_SM} onClick={() => setLocalEditor(null)} disabled={localBusy}>
                      {t("Cancel")}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="mt-2 text-[12px] text-muted">
                  <div className="truncate" title={localRow.path}>
                    {localRow.path}
                  </div>
                  {localError && <div className="text-danger mt-1">{localError}</div>}
                </div>
              )}
            </div>
          )}
          <div className="mt-4">
            {installed ? (
              <button className={BTN_BORDERED_SM} disabled data-testid="skill-installed-badge">
                {t("Installed")}
              </button>
            ) : installState === "idle" ? (
              <button
                className={BTN_ACCENT}
                onClick={() => setInstallState("confirm")}
                data-testid="skill-install-open"
              >
                {t("Install skill")}
              </button>
            ) : (
              <div className="rounded-lg border border-line bg-paper p-3.5" data-testid="skill-install-confirm">
                {scripts > 0 && (
                  <div className="text-[12.5px] text-muted mb-1.5">
                    {t(
                      "Contains {{count}} executable scripts; the model still asks your approval before running any of them.",
                      { count: scripts },
                    )}
                  </div>
                )}
                {compatibility && <div className="text-[12.5px] text-muted mb-2.5">{compatibility}</div>}
                {installState === "error" && (
                  <div className="text-[12.5px] text-danger mb-2">{installError}</div>
                )}
                <div className="flex items-center gap-2">
                  <button
                    className={BTN_ACCENT}
                    disabled={installState === "busy"}
                    onClick={doInstall}
                    data-testid="skill-install-confirm-btn"
                  >
                    {installState === "busy" ? t("Installing…") : t("Install skill")}
                  </button>
                  <button className={BTN_BORDERED_SM} onClick={() => setInstallState("idle")}>
                    {t("Cancel")}
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </ModalShell>
  );
}

// The expert editor (P4): one modal for "New expert" and "Edit prompt". Saving writes the
// machine-local file (an override for a pack expert; the expert's own file for a local
// one) and, for an installed expert, re-installs its coworker from the new text. Nothing
// here can touch the pack. Escape / backdrop close it — with a confirm when there are
// unsaved changes, so a stray click never eats a long prompt.
function ExpertEditorModal({
  editor,
  categories,
  fetchPrompt,
  onClose,
  onSaved,
}: {
  editor: ExpertEditor;
  categories: { category: string; categoryName: string }[];
  fetchPrompt: (lib: "zh" | "en", id: string) => Promise<PromptResult | null>;
  onClose: () => void;
  onSaved: (res: { id: string; created: boolean; reinstalled?: string[]; name: string }) => void;
}) {
  const { t } = useTranslation();
  const isEdit = editor.mode === "edit";
  const [loaded, setLoaded] = useState<PromptResult | null | undefined>(isEdit ? undefined : null);
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState(categories[0]?.category || "local");
  const [customCategory, setCustomCategory] = useState("");
  const [prompt, setPrompt] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const promptRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!isEdit) return;
    let live = true;
    setLoaded(undefined);
    fetchPrompt(editor.lib, editor.id).then((r) => {
      if (!live) return;
      setLoaded(r);
      if (r) {
        setName(r.meta?.name || r.name || "");
        setEmoji(r.meta?.emoji || "");
        setDescription(r.meta?.description || "");
        // A category the pack doesn't know (a local expert's own) reopens as "Custom…"
        // with its NAME in the box — not its internal slug (audit 2026-09-10).
        const known = categories.some((c) => c.category === r.meta?.category);
        if (known) setCategory(r.meta?.category || "local");
        else {
          setCategory("__custom__");
          setCustomCategory(r.meta?.categoryName || r.meta?.category || "");
        }
        setPrompt(r.prompt);
      }
    });
    return () => {
      live = false;
    };
  }, [isEdit, editor, fetchPrompt]);

  const close = () => {
    if (dirty && !window.confirm(t("Discard your unsaved changes?"))) return;
    onClose();
  };

  // A local expert keeps whatever category it was given (free text); a pack expert's
  // category is the pack's and stays read-only — the override changes its text, not
  // where it is filed.
  const categoryEditable = !isEdit || editor.local;
  const customPicked = category === "__custom__";
  const knownCategory = categories.find((c) => c.category === category);
  const canSave = !!name.trim() && !!prompt.trim() && !saving && (!customPicked || !!customCategory.trim());

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    setError("");
    try {
      const cat = customPicked ? customCategory.trim() : category;
      const catName = customPicked ? customCategory.trim() : knownCategory?.categoryName || loaded?.meta?.categoryName || cat;
      const res = await librarySaveExpert({
        lib: editor.lib,
        id: isEdit ? editor.id : undefined,
        name: name.trim(),
        description: description.trim(),
        emoji: emoji.trim(),
        color: loaded?.meta?.color || "",
        category: categoryEditable ? cat : loaded?.meta?.category || "",
        categoryName: categoryEditable ? catName : loaded?.meta?.categoryName || "",
        prompt,
      }).catch(() => ({ ok: false as const, error: t("unreachable") }));
      if (!res.ok || !res.id) {
        setError(res.error || t("Could not save this expert."));
        return;
      }
      setDirty(false);
      onSaved({ id: res.id, created: res.created === true, reinstalled: res.reinstalled, name: name.trim() });
    } finally {
      setSaving(false);
    }
  };

  const mark = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setDirty(true);
  };

  return (
    <ModalShell
      title={isEdit ? t("Edit {{name}}", { name: loaded?.name || editor.id }) : t("New expert")}
      sub={
        isEdit
          ? editor.local
            ? t("A local expert — saved on this machine only.")
            : t("Your edit is kept on this machine; the shipped original stays and can be restored.")
          : t("Saved on this machine only. It appears in the library like any other expert.")
      }
      onClose={close}
      testId="library-editor-modal"
      panelClassName="w-[760px]"
      z="z-[55]"
    >
      {loaded === undefined ? (
        <div className="text-[12.5px] text-muted">{t("Loading…")}</div>
      ) : isEdit && loaded === null ? (
        <div className="text-[12.5px] text-danger">{t("Could not load this prompt.")}</div>
      ) : (
        <>
          <div className="grid grid-cols-[1fr_88px] gap-3">
            <div>
              <label className={FIELD_LABEL} htmlFor="expert-name">
                {t("Name")}
              </label>
              <input
                id="expert-name"
                className={`${INPUT} mt-1`}
                value={name}
                placeholder={t("e.g. Production planner")}
                onChange={(e) => mark(setName)(e.target.value)}
                data-testid="expert-editor-name"
              />
            </div>
            <div>
              <label className={FIELD_LABEL} htmlFor="expert-emoji">
                {t("Emoji")}
              </label>
              <input
                id="expert-emoji"
                className={`${INPUT} mt-1 text-center`}
                value={emoji}
                placeholder="🧭"
                maxLength={8}
                onChange={(e) => mark(setEmoji)(e.target.value)}
                data-testid="expert-editor-emoji"
              />
            </div>
          </div>
          <div className="mt-3">
            <label className={FIELD_LABEL} htmlFor="expert-desc">
              {t("One-line description")}
            </label>
            <input
              id="expert-desc"
              className={`${INPUT} mt-1`}
              value={description}
              placeholder={t("What this expert is for — shown on the card")}
              onChange={(e) => mark(setDescription)(e.target.value)}
              data-testid="expert-editor-desc"
            />
          </div>
          <div className="mt-3">
            <label className={FIELD_LABEL} htmlFor="expert-category">
              {t("Category")}
            </label>
            {categoryEditable ? (
              <div className="flex gap-2 mt-1">
                <select
                  id="expert-category"
                  className={INPUT + " w-auto min-w-[180px]"}
                  value={customPicked || knownCategory ? category : "__custom__"}
                  onChange={(e) => mark(setCategory)(e.target.value)}
                  data-testid="expert-editor-category"
                >
                  {categories.map((c) => (
                    <option key={c.category} value={c.category}>
                      {c.categoryName}
                    </option>
                  ))}
                  <option value="__custom__">{t("Custom…")}</option>
                </select>
                {(customPicked || !knownCategory) && (
                  <input
                    className={INPUT}
                    value={customPicked ? customCategory : category}
                    placeholder={t("Category name")}
                    onChange={(e) => {
                      setDirty(true);
                      if (customPicked) setCustomCategory(e.target.value);
                      else setCategory(e.target.value);
                    }}
                    data-testid="expert-editor-category-custom"
                  />
                )}
              </div>
            ) : (
              <div className="text-[13px] text-muted mt-1">{loaded?.meta?.categoryName || "—"}</div>
            )}
          </div>
          <div className="mt-3">
            <div className="flex items-center gap-2">
              <label className={FIELD_LABEL} htmlFor="expert-prompt">
                {t("Prompt (markdown)")}
              </label>
              <span className="flex-1" />
              <span className="text-[11px] text-faint">
                {t("{{count}} characters", { count: prompt.length })}
              </span>
              {isEdit && !editor.local && loaded?.pack_prompt && loaded.pack_prompt !== prompt && (
                <button
                  className="text-[11.5px] text-muted hover:text-ink underline underline-offset-2"
                  onClick={() => {
                    mark(setPrompt)(loaded.pack_prompt || "");
                    promptRef.current?.focus();
                  }}
                  data-testid="expert-editor-reset-text"
                >
                  {t("Reset to shipped text")}
                </button>
              )}
            </div>
            <textarea
              id="expert-prompt"
              ref={promptRef}
              className={`${INPUT} mt-1 min-h-[320px] font-mono text-[12px] leading-relaxed`}
              value={prompt}
              spellCheck={false}
              placeholder={t("Who this expert is, what it does, how it answers…")}
              onChange={(e) => mark(setPrompt)(e.target.value)}
              onKeyDown={(e) => {
                // Ctrl/Cmd+S saves — the natural key in a text editor.
                if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s" && !isComposing(e)) {
                  e.preventDefault();
                  void save();
                }
              }}
              maxLength={MAX_EDITOR_PROMPT}
              data-testid="expert-editor-prompt"
            />
          </div>
          {error && (
            <div className="text-[12.5px] text-danger mt-2" data-testid="expert-editor-error">
              {error}
            </div>
          )}
          <div className="flex items-center gap-2 mt-3.5">
            <button className={BTN_ACCENT} disabled={!canSave} onClick={() => void save()} data-testid="expert-editor-save">
              {saving ? t("Saving…") : isEdit ? t("Save") : t("Create expert")}
            </button>
            <button className={BTN_BORDERED} onClick={close} disabled={saving}>
              {t("Cancel")}
            </button>
            {isEdit && !editor.local && (
              <span className="text-[11.5px] text-faint ml-auto">
                {t("Installed as a coworker? It is updated on save.")}
              </span>
            )}
          </div>
        </>
      )}
    </ModalShell>
  );
}

// The compact install-consent modal (LIBRARY-SPEC P2): same trust language as PersonasTab's
// ConsentCard (risk summary + exact-tools disclosure), trimmed to what a single already-fetched
// consent record needs — no replaces/recommends section, this is always a fresh install.
function ExpertConsentModal({
  flow,
  onClose,
  onConfirm,
}: {
  flow: ExpertFlow;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  const [showTools, setShowTools] = useState(false);
  const c = flow.consent?.[0];
  const busy = flow.status === "activating";

  const risk = c && c.risk.length ? c.risk : ["read"];
  const summary = riskSummary(t, risk);

  return (
    <ModalShell
      title={c?.name || flow.id}
      sub={flow.categoryName}
      onClose={onClose}
      testId="library-consent-modal"
      panelClassName="w-[440px]"
      z="z-[60]"
    >
      {flow.status === "error" ? (
        // The install call itself failed — there's no consent to show yet.
        <div className="text-[12.5px] text-danger" data-testid="library-consent-error">
          {flow.error}
        </div>
      ) : (
        <>
          {c?.description && <div className="text-[12.5px] text-muted mb-2">{c.description}</div>}
          <div className="text-[12.5px] text-ink">
            {t("Can {{summary}}", { summary })}
            {c?.connectors === "all"
              ? t(" · use ALL your connected services")
              : c?.connectors && c.connectors.length
                ? t(" · use connectors: {{list}}", { list: c.connectors.join(", ") })
                : ""}
            {c?.messaging ? t(" · send messages") : ""}
            {c?.mcp && c.mcp.length ? t(" · use MCP: {{list}}", { list: c.mcp.join(", ") }) : ""}
            <button
              className="ml-2 text-accent text-[12px] hover:underline"
              onClick={() => setShowTools((v) => !v)}
              data-testid="library-consent-tools-toggle"
            >
              {showTools ? t("Hide tools") : t("Exact tools ({{count}})", { count: c?.tools.length ?? 0 })}
            </button>
          </div>
          {showTools && (
            <div className="text-[12px] text-muted mt-1 font-mono">{(c?.tools || []).join(" · ") || "—"}</div>
          )}
          {flow.error && (
            <div className="text-[12.5px] text-danger mt-2" data-testid="library-consent-error">
              {flow.error}
            </div>
          )}
          <div className="flex items-center gap-2 mt-3.5">
            <button className={BTN_ACCENT} disabled={busy} onClick={onConfirm} data-testid="library-consent-confirm">
              {busy ? t("Enabling…") : flow.mode === "start" ? t("Enable and start") : t("Enable this coworker")}
            </button>
            <button className={BTN_BORDERED_SM} onClick={onClose} data-testid="library-consent-cancel">
              {t("Cancel")}
            </button>
          </div>
        </>
      )}
    </ModalShell>
  );
}

// One member's progress through the team-install pass: "skipped" means its worker variant
// was already installed+enabled (LIBRARY-SPEC P3 — "状态里 worker 已 enabled 的成员跳过安装
// 直接计入"), so it carries a personaId but no fresh consent record.
type TeamMemberResult = {
  member: TeamMember;
  status: "pending" | "installing" | "done" | "error";
  personaId?: string;
  consent?: PersonaConsent[];
  error?: string;
  skipped?: boolean;
};

// "Build an expert team" (LIBRARY-SPEC P3): install the "teammate" variant of every picked
// expert (serially, so the in-progress list reads top-to-bottom), then activate them all and
// hand the free-text goal + member names back to the caller to start an Expert Team Lead
// session. A failed install stops the pass in place — the completed rows stay marked done,
// Retry resumes from the failed one — rather than losing the whole pick to one bad install.
function ExpertTeamModal({
  members,
  expertsStatus,
  onClose,
  onDone,
}: {
  members: TeamMember[];
  expertsStatus: LibraryStatus["experts"] | undefined;
  onClose: () => void;
  onDone: (goal: string, names: string) => void;
}) {
  const { t } = useTranslation();
  const [goal, setGoal] = useState("");
  const [phase, setPhase] = useState<"form" | "installing" | "confirm">("form");
  const [results, setResults] = useState<TeamMemberResult[]>(
    members.map((member) => ({ member, status: "pending" })),
  );
  const [activating, setActivating] = useState(false);
  const [activateError, setActivateError] = useState<string | null>(null);
  // Guards setState calls in the async install/activate loops below against firing after
  // unmount. A plain `() => { live.current = false }` cleanup would misfire under
  // React 18 StrictMode's dev-only double-invoke (mount → cleanup → mount) — the first
  // synthetic cleanup would latch this false forever, since nothing else ever sets it back
  // to true. Resetting it at the top of the effect body fixes that: the second (real) mount
  // restores it before anything can observe the gap.
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  const runInstall = async (startFrom: number, seed: TeamMemberResult[]) => {
    setPhase("installing");
    let list = seed;
    for (let i = startFrom; i < members.length; i++) {
      const m = members[i];
      const existing = expertsStatus?.[teamKey(m)]?.worker;
      if (existing?.enabled) {
        list = list.map((r, idx) => (idx === i ? { ...r, status: "done", personaId: existing.persona_id, skipped: true } : r));
        if (!live.current) return;
        setResults(list);
        continue;
      }
      list = list.map((r, idx) => (idx === i ? { ...r, status: "installing" } : r));
      if (!live.current) return;
      setResults(list);
      const r = await libraryInstallExpert(m.lib, m.id, true).catch(() => ({ ok: false as const, error: t("unreachable") }));
      if (!live.current) return;
      if (!r.ok || !r.persona_id) {
        list = list.map((r2, idx) =>
          idx === i ? { ...r2, status: "error", error: r.error || t("Could not install this coworker.") } : r2,
        );
        setResults(list);
        return; // stop here — completed rows stay done, Retry picks up at i
      }
      list = list.map((r2, idx) => (idx === i ? { ...r2, status: "done", personaId: r.persona_id, consent: r.consent } : r2));
      setResults(list);
    }
    setPhase("confirm");
  };

  const retry = () => {
    const from = results.findIndex((r) => r.status === "error");
    void runInstall(from < 0 ? 0 : from, results);
  };

  const activateAndFinish = async () => {
    setActivating(true);
    setActivateError(null);
    for (const r of results) {
      if (r.skipped || !r.personaId) continue;
      const res = await libraryActivateExpert(r.personaId).catch(() => ({ ok: false as const, error: t("unreachable") }));
      if (!live.current) return;
      if (!res.ok) {
        setActivating(false);
        setActivateError(res.error || t("Could not enable this coworker."));
        return;
      }
    }
    setActivating(false);
    onDone(goal.trim(), results.map((r) => r.member.name).join(", "));
  };

  const errorRow = results.find((r) => r.status === "error");
  // Aggregate risk disclosure (spec: "取第一份 consent 的 risk 文案，全体同质") — every
  // teammate variant declares the same tool set, so the first fresh install's consent stands
  // in for all of them; a run where every member was already installed carries none, and the
  // line is simply omitted (nothing new to disclose).
  const sampleConsent = results.find((r) => r.consent && r.consent.length)?.consent?.[0];
  const summary = sampleConsent ? riskSummary(t, sampleConsent.risk.length ? sampleConsent.risk : ["read"]) : "";

  return (
    <ModalShell
      title={t("Build an expert team")}
      sub={t("{{count}} experts selected", { count: members.length })}
      onClose={onClose}
      testId="library-team-modal"
      panelClassName="w-[480px]"
    >
      {phase === "form" && (
        <>
          <textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder={t("Describe in one sentence what this expert team should accomplish…")}
            rows={3}
            className="w-full px-3 py-2 rounded-lg border border-line bg-paper text-[12.5px] text-ink outline-none focus:border-accent resize-none"
            data-testid="library-team-goal"
          />
          <div className="mt-3 space-y-1">
            {members.map((m) => (
              <div key={teamKey(m)} className="text-[12.5px] text-ink flex items-center gap-2">
                <span className="truncate">{m.name}</span>
                <span className="text-faint text-[11px] shrink-0">{m.categoryName}</span>
              </div>
            ))}
          </div>
          <div className="text-[12px] text-muted leading-relaxed mt-3">
            {t(
              "Installs a 'teammate' role for each expert (read/write files, search, run commands, and a task list), then opens an Expert Team Lead session to break the work into tasks and propose your team.",
            )}
          </div>
          <button
            className={BTN_ACCENT + " mt-3.5"}
            disabled={!goal.trim()}
            onClick={() => void runInstall(0, results)}
            data-testid="library-team-install"
          >
            {t("Install and start")}
          </button>
        </>
      )}

      {phase === "installing" && (
        <>
          <div className="space-y-1.5">
            {results.map((r) => (
              <div
                key={teamKey(r.member)}
                className="flex items-center gap-2 text-[12.5px]"
                data-testid={`library-team-progress-${r.member.id}`}
              >
                <span
                  className={
                    "shrink-0 " +
                    (r.status === "done" ? "text-ok" : r.status === "error" ? "text-danger" : "text-faint")
                  }
                  aria-hidden
                >
                  {r.status === "done" ? "✓" : r.status === "error" ? "✗" : r.status === "installing" ? "…" : "○"}
                </span>
                <span className="flex-1 min-w-0 truncate">{r.member.name}</span>
                {r.status === "installing" && (
                  <span className="text-faint text-[11px] shrink-0">
                    {t("Installing {{name}}…", { name: r.member.name })}
                  </span>
                )}
              </div>
            ))}
          </div>
          {errorRow && (
            <>
              <div className="text-[12.5px] text-danger mt-2" data-testid="library-team-error">
                {errorRow.error}
              </div>
              <button className={BTN_ACCENT + " mt-2.5"} onClick={retry} data-testid="library-team-retry">
                {t("Retry")}
              </button>
            </>
          )}
        </>
      )}

      {phase === "confirm" && (
        <>
          <div className="space-y-1 mb-3">
            {results.map((r) => (
              <div key={teamKey(r.member)} className="text-[12.5px] text-ink flex items-center gap-2">
                <span className="truncate">{r.member.name}</span>
                <span className="text-faint text-[11px] shrink-0">{r.member.categoryName}</span>
              </div>
            ))}
          </div>
          {sampleConsent && (
            <div className="text-[12.5px] text-ink mb-3" data-testid="library-team-consent-summary">
              {t("Can {{summary}}", { summary })}
              {sampleConsent.connectors === "all"
                ? t(" · use ALL your connected services")
                : sampleConsent.connectors.length
                  ? t(" · use connectors: {{list}}", { list: sampleConsent.connectors.join(", ") })
                  : ""}
              {sampleConsent.messaging ? t(" · send messages") : ""}
              {sampleConsent.mcp.length ? t(" · use MCP: {{list}}", { list: sampleConsent.mcp.join(", ") }) : ""}
            </div>
          )}
          {activateError && <div className="text-[12.5px] text-danger mb-2">{activateError}</div>}
          <div className="flex items-center gap-2">
            <button
              className={BTN_ACCENT}
              disabled={activating}
              onClick={() => void activateAndFinish()}
              data-testid="library-team-confirm"
            >
              {activating ? t("Enabling…") : t("Enable and create team")}
            </button>
            <button className={BTN_BORDERED_SM} onClick={onClose}>
              {t("Cancel")}
            </button>
          </div>
        </>
      )}
    </ModalShell>
  );
}
