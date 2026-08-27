// The Expert Library: browse/search over the bundled expert-prompt pack (zh + en) and the
// Skills pack (LIBRARY-SPEC P1), plus turning what you find into something the app actually
// runs (P2). Two content tabs share one search box and one category-chip row; each card opens
// a detail modal that lazy-fetches (and caches) the full prompt / SKILL.md text, with a
// one-click copy. An expert's "Start session" installs it as a persona (consent modal, same
// trust language as Settings ▸ Coworkers), enables it, and opens a session bound to it; a
// skill's detail modal installs it into the global skills directory the same way SkillsTab does.

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Markdown } from "./Markdown";
import {
  libraryActivateExpert,
  libraryExperts,
  libraryExpertPrompt,
  libraryInstallExpert,
  libraryInstallSkills,
  libraryOverview,
  librarySkillDetail,
  librarySkills,
  libraryStatus,
  type LibraryExpert,
  type LibraryExpertVariant,
  type LibrarySkill,
  type PersonaConsent,
} from "../api";
import { RISK_PHRASE } from "./PersonasTab";
import { Icon } from "./Icon";

const CARD = "rounded-xl border border-line bg-panel/60";
const CARD_SELECTED = "rounded-xl border border-accent bg-panel/60";
const BTN_ACCENT =
  "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";
const BTN_BORDERED =
  "text-[12px] px-2.5 py-1.5 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0 disabled:opacity-40";
const CHIP = "text-[10.5px] px-1.5 py-0.5 rounded border border-line text-muted shrink-0";
const PILL = "text-[11.5px] px-2.5 py-1 rounded-full border shrink-0";
const PILL_ON = PILL + " border-accent text-accent bg-accentSoft";
const PILL_OFF = PILL + " border-line text-muted hover:border-lineStrong";

// Expert-team multi-select (LIBRARY-SPEC P3): a pick-6 cap on how many experts one
// "build a team" pass can install teammate variants for in one go.
const MAX_TEAM_SIZE = 6;

type Tab = "experts" | "skills";
type PromptResult = { name: string; prompt: string };
type SkillResult = { name: string; description: string; skill_md: string; files: string[] };

type Detail =
  | { kind: "expert"; id: string; lib: "zh" | "en"; pair: boolean; categoryName: string }
  | { kind: "skill"; name: string; categoryName: string; scripts: number; compatibility?: string };

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
}: {
  // Opens a NEW session bound to this persona (the same "browse a persona, start a
  // session for it" mechanism the sidebar's own New-session action uses) and switches
  // back to the conversation surface. Expert roles never gate on a folder.
  onStartExpertSession: (personaId: string) => void;
  // Multi-select "build an expert team" (P3): once every picked expert's "teammate"
  // variant is installed + enabled, hands off the free-text goal and the member names
  // so the caller can start an Expert Team Lead session and prefill its composer.
  onStartTeamSession: (goal: string, names: string) => void;
}) {
  const { t } = useTranslation();
  const [overview, setOverview] = useState<{ ok: boolean } | null>(null);
  const [tab, setTab] = useState<Tab>("experts");
  const [lib, setLib] = useState<"zh" | "en">("zh");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("all");
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

  useEffect(() => {
    let live = true;
    setExperts(null);
    libraryExperts(lib)
      .then((e) => live && setExperts(e))
      .catch(() => live && setExperts([]));
    return () => {
      live = false;
    };
  }, [lib, reloadTick]);

  // Category chips are per-dataset — reset the filter whenever the dataset underneath
  // them changes so a stale selection never silently hides everything.
  useEffect(() => {
    setCategory("all");
  }, [tab, lib]);

  // Stable identities (refs only, no reactive deps) — so an open detail modal's fetch effect
  // never re-fires just because the page behind it re-rendered (a search keystroke, etc.).
  const fetchPrompt = useCallback(async (l: "zh" | "en", id: string): Promise<PromptResult | null> => {
    const key = `${l}:${id}`;
    const cached = promptCache.current.get(key);
    if (cached) return cached;
    const r = await libraryExpertPrompt(l, id);
    if (r) promptCache.current.set(key, r);
    return r;
  }, []);

  const fetchSkill = useCallback(async (name: string): Promise<SkillResult | null> => {
    const cached = skillCache.current.get(name);
    if (cached) return cached;
    const r = await librarySkillDetail(name);
    if (r) skillCache.current.set(name, r);
    return r;
  }, []);

  // Step 1 of install→consent→enable: convert the library entry into an installed (but
  // disabled/unsurfaced) persona and open the compact consent modal on its result. The
  // caller (a card or the detail modal) awaits this to know when to drop its own busy state.
  const beginExpertFlow = useCallback(
    async (l: "zh" | "en", id: string, categoryName: string, mode: ExpertFlow["mode"]) => {
      const r = await libraryInstallExpert(l, id);
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
    const r = await libraryActivateExpert(personaId);
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
    const r = await libraryInstallSkills([name]);
    if (!r.ok) return { ok: false, error: r.error };
    const item = (r.results || []).find((x) => x.name === name);
    if (item && !item.ok) return { ok: false, error: item.error };
    loadStatus();
    return { ok: true };
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
      (!q || `${s.name} ${s.description} ${s.categoryName}`.toLowerCase().includes(q)),
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
          </div>

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
                <button
                  onClick={() => removeTeamMember(teamKey(m))}
                  aria-label={`${t("Remove")}: ${m.name}`}
                  className="text-faint hover:text-ink"
                >
                  ×
                </button>
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
          <button className={BTN_BORDERED} onClick={cancelTeamMode}>
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
    await onInstallForStart(lib, entry.id, entry.categoryName);
    setStartBusy(false);
  };

  const installed = variant?.enabled === true;

  return (
    <div
      className={(teamMode && teamSelected ? CARD_SELECTED : CARD) + " p-3.5 flex flex-col" + (teamMode ? " cursor-pointer" : "")}
      data-testid={`expert-card-${entry.id}`}
      onClick={teamMode ? onToggleTeamSelect : undefined}
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
          <span
            className={
              "w-4 h-4 rounded border shrink-0 grid place-items-center text-[10px] leading-none " +
              (teamSelected ? "border-accent bg-accent text-white" : "border-line text-transparent")
            }
            aria-hidden
            data-testid={`expert-team-check-${entry.id}`}
          >
            ✓
          </span>
        ) : (
          installed && (
            <span className={CHIP} data-testid={`expert-installed-chip-${entry.id}`}>
              {t("Installed")}
            </span>
          )
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
        <button className={BTN_BORDERED} onClick={(e) => { e.stopPropagation(); onView(); }}>
          {t("View prompt")}
        </button>
        <button
          className={BTN_BORDERED}
          onClick={(e) => { e.stopPropagation(); void doCopy(); }}
          disabled={copyState === "busy"}
        >
          {copyState === "copied" ? t("Copied") : copyState === "error" ? t("Copy failed") : t("Copy prompt")}
        </button>
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
        {entry.description}
      </div>
      <div className="flex items-center justify-between gap-2">
        <button className={BTN_BORDERED} onClick={onView}>
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
      if (e.key === "Escape") onClose();
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
          <button
            className="text-faint hover:text-ink shrink-0"
            onClick={onClose}
            aria-label={t("Close")}
            data-testid={`${testId}-close`}
          >
            <Icon name="x" size={16} />
          </button>
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
}: {
  id: string;
  initialLib: "zh" | "en";
  pair: boolean;
  categoryName: string;
  onClose: () => void;
  fetchPrompt: (lib: "zh" | "en", id: string) => Promise<PromptResult | null>;
  expertsStatus: LibraryStatus["experts"] | undefined;
  onInstallAsCoworker: (lib: "zh" | "en", id: string, categoryName: string) => Promise<void>;
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
    await onInstallAsCoworker(curLib, id, categoryName);
    setInstallBusy(false);
  };

  return (
    <ModalShell
      title={data?.name || id}
      sub={categoryName}
      onClose={onClose}
      headerExtra={
        pair && (
          <button
            className={BTN_BORDERED}
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
          {/* Rendered markdown (the packs are authored in md); Copy still hands over the raw text. */}
          <div className="text-[13px] bg-paper rounded-lg border border-line px-3.5 py-1" data-testid="expert-prompt-md">
            <Markdown text={data.prompt} />
          </div>
          <div className="flex items-center gap-2 mt-3">
            <button className={BTN_ACCENT} onClick={doCopy}>
              {copyState === "copied" ? t("Copied") : copyState === "error" ? t("Copy failed") : t("Copy")}
            </button>
            {installed ? (
              <button className={BTN_BORDERED} disabled data-testid="expert-installed-badge">
                {t("Installed")}
              </button>
            ) : (
              <button
                className={BTN_BORDERED}
                disabled={installBusy}
                onClick={handleInstall}
                data-testid="expert-install-as-coworker"
              >
                {installBusy ? t("Installing…") : t("Install as coworker")}
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
}: {
  name: string;
  categoryName: string;
  scripts: number;
  compatibility?: string;
  installed: boolean;
  onClose: () => void;
  fetchSkill: (name: string) => Promise<SkillResult | null>;
  onInstall: (name: string) => Promise<{ ok: boolean; error?: string }>;
}) {
  const { t } = useTranslation();
  const [data, setData] = useState<SkillResult | null | undefined>(undefined); // undefined = loading
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  // "confirm" reveals the scripts/compatibility disclosure block (spec: no silent installs
  // of a skill that ships executable scripts) before the actual install call fires.
  const [installState, setInstallState] = useState<"idle" | "confirm" | "busy" | "error">("idle");
  const [installError, setInstallError] = useState("");

  useEffect(() => {
    let live = true;
    setData(undefined);
    fetchSkill(name).then((r) => live && setData(r));
    return () => {
      live = false;
    };
  }, [name, fetchSkill]);

  const doCopy = async () => {
    if (!data) return;
    const ok = await copyText(data.skill_md);
    setCopyState(ok ? "copied" : "error");
    window.setTimeout(() => setCopyState("idle"), 1500);
  };

  const doInstall = async () => {
    setInstallState("busy");
    const r = await onInstall(name);
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
    <ModalShell title={data?.name || name} sub={categoryName} onClose={onClose}>
      {data === undefined ? (
        <div className="text-[12.5px] text-muted">{t("Loading…")}</div>
      ) : data === null ? (
        <div className="text-[12.5px] text-danger">{t("Could not load this skill.")}</div>
      ) : (
        <>
          {data.description && <div className="text-[12.5px] text-muted mb-3">{data.description}</div>}
          <div className="text-[13px] bg-paper rounded-lg border border-line px-3.5 py-1" data-testid="skill-md">
            <Markdown text={data.skill_md} />
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
          <div className="mt-4">
            {installed ? (
              <button className={BTN_BORDERED} disabled data-testid="skill-installed-badge">
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
                  <button className={BTN_BORDERED} onClick={() => setInstallState("idle")}>
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
            <button className={BTN_BORDERED} onClick={onClose} data-testid="library-consent-cancel">
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
      const r = await libraryInstallExpert(m.lib, m.id, true);
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
      const res = await libraryActivateExpert(r.personaId);
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
            <button className={BTN_BORDERED} onClick={onClose}>
              {t("Cancel")}
            </button>
          </div>
        </>
      )}
    </ModalShell>
  );
}
