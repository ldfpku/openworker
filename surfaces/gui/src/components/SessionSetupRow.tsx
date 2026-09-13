import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { getRecentWorkspaces, openWorkspace, type Persona, type RecentWorkspace } from "../api";
import { chooseFolder } from "../tauri";
import { fullPersonaName } from "../personaScope";
import { BASELINE_PERSONA } from "../personaLifecycle";
import { baseName } from "../paths";
import { Icon } from "./Icon";
import { IconButton } from "./IconButton";
import { Toggle } from "./Toggle";

// UX-029: the session-setup row — per-SESSION choices (coworker + folder) in their own
// quiet chip row above the composer, a different species from the per-MESSAGE controls
// inside it. Rendered only before the first message; after that the whole row leaves and
// its facts move to the session header. Chips are borderless (position, not a border,
// marks them as different) and the coworker chip carries no icon — both owner calls.
//
// The coworker menu (owner ask 2026-09-10) is also where a coworker is switched OFF for
// this session — a switch at its top: off = the general OpenWorker coworker with no
// specialist prompt, on = the last specialist picked. Every row has a "View" so what a
// coworker actually says to the model can be read before (or after) picking it.

// The general-purpose coworker every session falls back to when no specialist is picked.
// Declared once, in personaLifecycle.ts — the module that also owns the repair rule that
// must never fire for it; re-exported here under this file's older name.
export const GENERAL_PERSONA = BASELINE_PERSONA;
// Where the last specialist pick is remembered across drafts (localStorage — a preference
// of this machine, not of any session).
const LAST_SPECIALIST_KEY = "openworker.lastSpecialistCoworker";

interface Props {
  personas: Persona[] | null;
  agent: string;
  // The folder chip renders only for personas that work in a folder (Chat hides it).
  showFolder: boolean;
  // The user's explicit folder pick for this draft, if any (never a temporary dir's path).
  folderName: string | null;
  onPickCoworker: (id: string) => void;
  onPickFolder: (path: string, branch?: string | null) => void;
  onManage: () => void;
  // Sharing v1 (OPE-7): the quick door to the import/browse screen — one row, so the
  // picker itself never grows beyond the user's own coworkers.
  onImport: () => void;
  // Open the read-only look at one coworker (PersonaPeek): identity + its instructions.
  onPeek?: (id: string) => void;
}

function readLastSpecialist(): string | null {
  try {
    return localStorage.getItem(LAST_SPECIALIST_KEY);
  } catch {
    return null;
  }
}

function rememberLastSpecialist(id: string) {
  try {
    localStorage.setItem(LAST_SPECIALIST_KEY, id);
  } catch {
    /* storage unavailable — the in-memory ref still covers this session */
  }
}

export function SessionSetupRow(props: Props) {
  const { t } = useTranslation();
  const [openMenu, setOpenMenu] = useState<"coworker" | "folder" | null>(null);
  const [recents, setRecents] = useState<RecentWorkspace[] | null>(null);
  const [error, setError] = useState("");
  // Enabled-but-unsurfaced personas (library experts) stay out of the picker; the one
  // bound to THIS draft still renders so the chip never lies about the session — and so
  // does the one the switch below would bring back, or "on" would have nothing to show.
  const enabled = (props.personas || []).filter((p) => p.enabled);
  const specialistOn = props.agent !== GENERAL_PERSONA;
  // The specialist to come back to when the switch flips on again: the current one while
  // it is on, else the last one picked (this draft, or an earlier one on this machine —
  // a library expert counts even though it never surfaces in the picker), else the first
  // specialist the picker offers. No specialist at all → the switch is moot and hides.
  const lastSpecialist = useRef<string | null>(readLastSpecialist());
  useEffect(() => {
    if (specialistOn) {
      lastSpecialist.current = props.agent;
      rememberLastSpecialist(props.agent);
    }
  }, [props.agent, specialistOn]);
  const remembered = lastSpecialist.current;
  const rememberedEnabled = !!remembered && enabled.some((p) => p.id === remembered);
  const personas = enabled.filter(
    (p) => p.surfaced || p.id === props.agent || (rememberedEnabled && p.id === remembered),
  );
  const current = enabled.find((p) => p.id === props.agent);
  const specialists = personas.filter((p) => p.id !== GENERAL_PERSONA);
  const resumeSpecialist =
    (rememberedEnabled && remembered !== GENERAL_PERSONA ? remembered : null) ||
    specialists[0]?.id ||
    null;

  const toggle = (menu: "coworker" | "folder") => {
    setError("");
    if (menu === "folder" && openMenu !== "folder") {
      getRecentWorkspaces().then(setRecents).catch(() => setRecents([]));
    }
    setOpenMenu((cur) => (cur === menu ? null : menu));
  };

  const pickFolder = async (path: string) => {
    const res = await openWorkspace(path);
    if (!res.ok) {
      setError(res.error || t("folder_gate.open_error"));
      return;
    }
    setOpenMenu(null);
    props.onPickFolder(res.path, res.git_branch);
  };

  const browse = async () => {
    const picked = await chooseFolder();
    if (picked) await pickFolder(picked);
  };

  const chip =
    "relative inline-flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-[13px] text-muted hover:text-ink hover:bg-paper cursor-pointer select-none whitespace-nowrap";

  // Naming: the general coworker reads as "OpenWorker (general)" here rather than the
  // family word ("Coworker"/"协作代理"), which in THIS menu would be indistinguishable from
  // the menu's own subject.
  const rowName = (p: Persona) =>
    p.id === GENERAL_PERSONA ? t("setup.general_coworker") : fullPersonaName(p.name, p.id);
  const chipName = specialistOn
    ? fullPersonaName(current?.name, props.agent)
    : t("setup.general_coworker");

  return (
    <div className="max-w-3xl mx-auto mb-1.5 px-1 flex items-center gap-1.5" data-testid="setup-row">
      {openMenu && <div className="fixed inset-0 z-20" onClick={() => setOpenMenu(null)} />}

      {/* Coworker chip — name only, no icon (owner call). */}
      <div className="relative">
        <button className={chip} data-testid="coworker-chip" onClick={() => toggle("coworker")}>
          {chipName}
          <Icon name="chevronDown" size={12} className="text-faint" />
        </button>
        {openMenu === "coworker" && (
          <div className="setup-menu absolute bottom-full mb-1.5 left-0 z-30 w-[340px] bg-panel border border-line rounded-xl2 shadow-xl p-1">
            {/* The switch: use a specialist coworker for this session, or not. */}
            {resumeSpecialist && (
              <div
                className="flex items-center gap-2.5 px-2.5 py-2 mb-1 border-b border-line"
                data-testid="coworker-switch-row"
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-[12.5px] font-medium text-ink">
                    {t("setup.use_specialist")}
                  </span>
                  <span className="block text-[11.5px] text-muted leading-snug">
                    {specialistOn ? t("setup.use_specialist_on") : t("setup.use_specialist_off")}
                  </span>
                </span>
                <Toggle
                  checked={specialistOn}
                  label={t("setup.use_specialist")}
                  onChange={(on) => {
                    const target = on ? resumeSpecialist : GENERAL_PERSONA;
                    if (target && target !== props.agent) props.onPickCoworker(target);
                  }}
                />
              </div>
            )}
            {personas.map((p) => (
              <div
                key={p.id}
                className={
                  "w-full flex items-center gap-1 rounded-lg hover:bg-paper " +
                  (p.id === props.agent ? "bg-accentSoft/50" : "")
                }
                data-testid={`coworker-row-${p.id}`}
              >
                <button
                  className="min-w-0 flex-1 text-left px-2.5 py-2"
                  onClick={() => {
                    setOpenMenu(null);
                    props.onPickCoworker(p.id);
                  }}
                >
                  <span className="block text-[13px] font-medium text-ink truncate">{rowName(p)}</span>
                  {p.tagline && (
                    <span className="block text-[12px] text-muted truncate">{t(p.tagline)}</span>
                  )}
                </button>
                {props.onPeek && (
                  <IconButton
                    icon="book"
                    size={14}
                    small
                    className="mr-1 shrink-0"
                    label={t("setup.view_coworker")}
                    data-testid={`coworker-peek-${p.id}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenMenu(null);
                      props.onPeek?.(p.id);
                    }}
                  />
                )}
              </div>
            ))}
            <div className="border-t border-line mt-1 pt-1">
              <button
                className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-paper text-[12px] text-accent"
                data-testid="import-coworker"
                onClick={() => {
                  setOpenMenu(null);
                  props.onImport();
                }}
              >
                {t("setup.import_coworker")}
              </button>
              <button
                className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-paper text-[12px] text-accent"
                onClick={() => {
                  setOpenMenu(null);
                  props.onManage();
                }}
              >
                {t("setup.manage_coworkers")}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Folder chip — only for personas that work in a folder. */}
      {props.showFolder && (
        <div className="relative">
          <button className={chip} data-testid="folder-chip" onClick={() => toggle("folder")}>
            <Icon name="folder" size={13} />
            <span className="max-w-[220px] truncate">
              {props.folderName || t("setup.choose_folder")}
            </span>
            <Icon name="chevronDown" size={12} className="text-faint" />
          </button>
          {openMenu === "folder" && (
            <div className="setup-menu absolute bottom-full mb-1.5 left-0 z-30 w-[280px] bg-panel border border-line rounded-xl2 shadow-xl p-1">
              {(recents || [])
                .filter((w) => w.exists)
                .slice(0, 5)
                .map((w) => (
                  <button
                    key={w.path}
                    className="w-full text-left flex items-start gap-2.5 px-2.5 py-2 rounded-lg hover:bg-paper"
                    onClick={() => void pickFolder(w.path)}
                    title={w.path}
                  >
                    <Icon name="folder" size={13} className="mt-0.5 shrink-0 text-muted" />
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium text-ink truncate">{baseName(w.path)}</span>
                      <span className="block text-[12px] text-faint truncate">{w.path}</span>
                    </span>
                  </button>
                ))}
              <div className={(recents || []).some((w) => w.exists) ? "border-t border-line mt-1 pt-1" : ""}>
                <button
                  className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-paper text-[12px] text-accent"
                  onClick={() => void browse()}
                >
                  {props.folderName ? t("setup.choose_another_folder") : t("setup.choose_a_folder")}
                </button>
              </div>
              {error && <div className="px-2.5 py-1 text-[12px] text-warnInk">{error}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
