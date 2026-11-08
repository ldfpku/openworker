import { isComposing } from "../ime";
import { useEffect, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import {
  applySkillUpdates,
  checkSkillUpdates,
  createSkill,
  deleteSkill,
  getSkillUpdates,
  listSkills,
  listSkillSources,
  revealSkill,
  rollbackSkill,
  setSkillInvocation,
  stageSkillUpload,
  importSkillFolder,
  confirmSkillUpload,
  updateSkill,
  type SkillApplyResult,
  type SkillRow,
  type SkillSource,
  type SkillUpdatesView,
  type SkillUploadPreview,
} from "../api";
import { chooseFolder, isTauri } from "../tauri";
import { BTN_ACCENT, BTN_BORDERED } from "./buttons";
import { Icon } from "./Icon";
import { IconButton } from "./IconButton";
import { SkillSourcesPanel, sourceName } from "./SkillSourcesPanel";
import { Toggle } from "./Toggle";

// Settings ▸ Skills (SKILLS-SPEC §5/§6) — the management home: the LIST is the page; every
// add-surface appears only when summoned from the single "Add skill" menu (the three doors:
// write form / import / start-a-conversation). Everything a user creates here is GLOBAL —
// "skills are things your worker knows everywhere". Creation-by-AI is a CONVERSATION (the
// menu's third door starts one; the worker proposes via save_skill) — there is no
// in-Settings drafting and no description box: the composer is where you describe it.
// Persona-bundled skills arrive with personas (§10), managed on the persona page, not here.

const CARD = "rounded-xl2 border border-line bg-panel";
const FIELD_LABEL = "text-[13px] font-medium text-ink";
const INPUT =
  "w-full min-w-0 px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";
const BADGE =
  "text-[11px] px-2 py-0.5 rounded-full border border-line bg-paper text-muted shrink-0";

type Editor = {
  mode: "new" | "edit";
  name: string;
  description: string;
  instructions: string;
};

const emptyEditor = (): Editor => ({
  mode: "new",
  name: "",
  description: "",
  instructions: "",
});

// 来源与升级 §5–§7 — update states and the batch-upgrade selection.
type Filter = "all" | "own" | "external" | "updates";
const UPGRADABLE = new Set(["available", "modified_and_available"]);
const rowKey = (r: SkillRow) => `${r.origin ?? "own"}:${r.name}`;
const isUpgradable = (r: SkillRow) => UPGRADABLE.has(r.update?.status ?? "");
const isModified = (r: SkillRow) =>
  r.update?.status === "modified" || r.update?.status === "modified_and_available";

function statusChip(
  t: (k: string, o?: Record<string, unknown>) => string,
  row: SkillRow,
): { text: string; tone: "accent" | "warn" | "muted" | "faint"; title?: string } | null {
  const u = row.update;
  if (!u) return null;
  const origin = row.origin ?? "own";
  switch (u.status) {
    case "available":
      return { text: t("skills.status_available"), tone: "accent" };
    case "modified_and_available":
      return {
        text: t("skills.status_modified_and_available"),
        tone: "warn",
        title: u.modified_unknown ? t("skills.modified_unknown_tip") : undefined,
      };
    case "modified":
      return { text: t("skills.status_modified"), tone: "warn" };
    case "up_to_date":
      return { text: t("skills.status_up_to_date"), tone: "faint" };
    case "error":
      return { text: t("skills.status_error"), tone: "warn", title: u.error };
    case "unsupported":
      return { text: t("skills.status_unsupported"), tone: "faint", title: u.error };
    case "unchecked":
      return { text: t("skills.status_unchecked"), tone: "faint" };
    case "untracked":
      return origin === "external"
        ? { text: t("skills.status_untracked_external"), tone: "faint" }
        : { text: t("skills.status_untracked"), tone: "faint" };
    default:
      return null;
  }
}

const CHIP_TONE = {
  accent: "border-accent/40 text-accent bg-paper",
  warn: "border-warnInk/30 text-warnInk bg-warnSoft/60",
  muted: "border-line text-muted bg-paper",
  faint: "border-transparent text-faint",
} as const;

function formatChecked(t: (k: string, o?: Record<string, unknown>) => string, at?: number | null) {
  if (!at) return t("skills.never_checked");
  return t("skills.last_checked", { when: new Date(at * 1000).toLocaleString() });
}

async function fileToB64(file: File): Promise<string> {
  // FileReader fallback: File.arrayBuffer is missing in some webviews (and jsdom).
  const buf =
    typeof file.arrayBuffer === "function"
      ? await file.arrayBuffer()
      : await new Promise<ArrayBuffer>((resolve, reject) => {
          const r = new FileReader();
          r.onload = () => resolve(r.result as ArrayBuffer);
          r.onerror = () => reject(r.error);
          r.readAsArrayBuffer(file);
        });
  const bytes = new Uint8Array(buf);
  let bin = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(bin);
}

export function SkillsTab({
  onCreateSkill,
  onUpdateCount,
}: {
  // The doorway (SKILLS-SPEC §5.2): starts a new conversation with the description
  // prefilled in the composer — the worker builds the skill and proposes it via save_skill.
  onCreateSkill?: (description: string) => void;
  /** How many listed skills can be upgraded — the Settings nav shows it as a badge. */
  onUpdateCount?: (count: number) => void;
}) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<SkillRow[]>([]);
  // 来源与升级 §1, §6–§7.
  const [sources, setSources] = useState<SkillSource[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const [checking, setChecking] = useState(false);
  const [applying, setApplying] = useState(false);
  // Keys the person ticked (or that were ticked by default); `seen` remembers which
  // upgradable rows already got their default, so a refresh never re-ticks one they cleared.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const seenUpgradable = useRef<Set<string>>(new Set());
  const [confirmModified, setConfirmModified] = useState<SkillRow[] | null>(null);
  const [results, setResults] = useState<SkillApplyResult[] | null>(null);
  // A rejected fetch must not read as "genuinely no skills" — track it separately so the
  // empty-state copy only shows for an actual empty list, and a failure gets its own
  // retryable message instead.
  const [loadFailed, setLoadFailed] = useState(false);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [upload, setUpload] = useState<SkillUploadPreview | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [armedDelete, setArmedDelete] = useState<string | null>(null);
  const [error, setError] = useState("");
  // The state-change callout (SKILLS-SPEC §4.1 #2): name-first so the user knows WHICH
  // skill, and visually distinct so it can't be skimmed past (tester ask 2026-07-27).
  const [notice, setNotice] = useState<{ name: string; text: string; tone: "ok" | "warn" } | null>(
    null,
  );
  const fileInput = useRef<HTMLInputElement>(null);

  // Confirmation copy (SKILLS-SPEC §4.1 #2): name-first, outcome + remedy only, in words a
  // person already owns — now / everywhere / off / start a new one. Never mechanism ("the
  // model will be told…") or engineering timing ("from the next message") — owner-driver
  // review rounds, 2026-07-27. The engine countermands disabled-but-loaded skills silently;
  // the copy promises only the guaranteed part.
  const CONFIRMATION = t("skills.confirmation");
  const OFF_NOTE = t("skills.off_note");
  const DELETE_NOTE = t("skills.delete_note");

  const applyRows = (next: SkillRow[]) => {
    setRows(next);
    // Default selection (来源与升级 §7): a plain update is ticked, one over local changes is
    // not — overwriting those must be a deliberate choice.
    const upgradable = next.filter(isUpgradable);
    // Work out the newly-seen defaults OUTSIDE the state updater: React may run an updater
    // twice (StrictMode), and one that mutated the ref would skip the default the 2nd time.
    const fresh = upgradable.filter((r) => !seenUpgradable.current.has(rowKey(r)));
    for (const r of fresh) seenUpgradable.current.add(rowKey(r));
    const defaults = fresh.filter((r) => !isModified(r)).map(rowKey);
    setSelected((prev) => {
      const out = new Set([...prev].filter((k) => upgradable.some((r) => rowKey(r) === k)));
      for (const k of defaults) out.add(k);
      return out;
    });
    onUpdateCount?.(upgradable.length);
  };

  const refresh = () => {
    setLoadFailed(false);
    listSkills()
      .then(applyRows)
      // Keep already-loaded rows on a failed refresh; only a never-loaded list stays empty.
      .catch(() => setLoadFailed(true));
  };

  const runCheck = async () => {
    setChecking(true);
    try {
      const view: SkillUpdatesView = await checkSkillUpdates();
      if (view.ok === false) setError(view.error || t("skills.check_failed"));
      else setCheckedAt(view.checked_at ?? null);
    } finally {
      setChecking(false);
      refresh();
    }
  };

  useEffect(() => {
    refresh();
    listSkillSources()
      .then((res) => res.sources && setSources(res.sources))
      .catch(() => undefined);
    // Background check when the last one is over a day old (来源与升级 §6).
    getSkillUpdates()
      .then((view) => {
        if (view.ok === false) return;
        setCheckedAt(view.checked_at ?? null);
        if (view.stale) void runCheck();
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Disarming the two-step delete: a press anywhere but the confirm button, or Escape.
  // Not `onBlur` alone — WebKit (the macOS app's webview) does not treat a <button> as
  // mouse-focusable and clears focus on mousedown, so the autofocused confirm button
  // blurred on the very press meant to confirm it, was swapped back to the trash icon
  // before mouseup, and the click never landed: skills could not be deleted on a Mac
  // (user report 2026-10-13). Chromium keeps focus on a clicked button, which is why
  // Windows and the jsdom tests never saw it.
  useEffect(() => {
    if (!armedDelete) return;
    const onDown = (e: Event) => {
      const el = e.target instanceof Element ? e.target : null;
      if (!el?.closest("[data-confirm-delete]")) setArmedDelete(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !isComposing(e)) setArmedDelete(null);
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [armedDelete]);

  const fail = (res: { ok?: boolean; error?: string }) => {
    setNotice(null);
    if (res.ok === false) {
      setError(res.error || t("skills.error_generic"));
      return true;
    }
    setError("");
    return false;
  };

  const save = async () => {
    if (!editor) return;
    const res =
      editor.mode === "new"
        ? await createSkill({
            name: editor.name.trim(),
            description: editor.description.trim(),
            instructions: editor.instructions,
          })
        : await updateSkill(editor.name, {
            description: editor.description.trim(),
            instructions: editor.instructions,
          });
    if (fail(res)) return;
    setEditor(null);
    if (editor.mode === "new")
      setNotice({ name: editor.name.trim(), text: CONFIRMATION, tone: "ok" });
    refresh();
  };

  const onPickFile = async (file: File | undefined) => {
    if (!file) return;
    const res = await stageSkillUpload(await fileToB64(file), file.name);
    if (fail(res)) return;
    setUpload(res);
  };

  // Desktop only (it needs a native folder picker). Importing the folder itself removes
  // the packaging step, and with it the usual way junk gets in: nobody prunes
  // __pycache__ before zipping. Same staging → preview → confirm as an upload.
  const onPickFolder = async () => {
    const path = await chooseFolder();
    if (!path) return;
    const res = await importSkillFolder(path);
    if (fail(res)) return;
    setUpload(res);
  };

  const confirmUpload = async () => {
    if (!upload?.token) return;
    const res = await confirmSkillUpload(upload.token);
    if (fail(res)) return;
    setUpload(null);
    setNotice({ name: upload.name || t("skills.fallback_name"), text: CONFIRMATION, tone: "ok" });
    refresh();
  };

  const remove = async (row: SkillRow) => {
    if (armedDelete !== row.name) {
      setArmedDelete(row.name);
      return;
    }
    setArmedDelete(null);
    const res = await deleteSkill(row.name);
    // Refresh either way: a refused delete must leave the list showing what is really
    // on disk, not what the click hoped for.
    refresh();
    if (fail(res)) return;
    setNotice({ name: row.name, text: DELETE_NOTE, tone: "warn" });
  };

  // -- upgrades (来源与升级 §7) ---------------------------------------------------------
  const selectedRows = rows.filter((r) => isUpgradable(r) && selected.has(rowKey(r)));

  const toggleSelected = (row: SkillRow, on: boolean) =>
    setSelected((prev) => {
      const out = new Set(prev);
      if (on) out.add(rowKey(row));
      else out.delete(rowKey(row));
      return out;
    });

  const upgrade = async (overwrite: boolean) => {
    const picked = selectedRows;
    if (!picked.length) return;
    const modified = picked.filter(isModified);
    if (modified.length && !overwrite) {
      setConfirmModified(modified);
      return;
    }
    setConfirmModified(null);
    setApplying(true);
    setResults(null);
    try {
      const res = await applySkillUpdates(
        picked.map((r) => ({
          name: r.name,
          origin: r.origin ?? "own",
          overwrite_modified: overwrite && isModified(r),
        })),
      );
      if (fail(res)) return;
      setResults(res.results ?? []);
    } finally {
      setApplying(false);
      refresh();
    }
  };

  const rollback = async (row: SkillRow) => {
    const res = await rollbackSkill(row.name, row.origin ?? "own");
    refresh();
    if (fail(res)) return;
    setNotice({
      name: row.name,
      text: res.warning ? `${t("skills.rolled_back")} ${res.warning}` : t("skills.rolled_back"),
      tone: "ok",
    });
  };

  const setInvocation = async (row: SkillRow, mode: "auto" | "manual") => {
    const res = await setSkillInvocation(row.name, mode);
    refresh();
    if (fail(res)) return;
    setNotice({
      name: row.name,
      text: mode === "auto" ? t("skills.invocation_auto_note") : t("skills.invocation_manual_note"),
      tone: "ok",
    });
  };

  const upgradableCount = rows.filter(isUpgradable).length;
  const hasExternal = rows.some((r) => r.origin === "external");
  const visibleRows = rows.filter((r) => {
    if (filter === "own") return r.origin !== "external";
    if (filter === "external") return r.origin === "external";
    if (filter === "updates") return isUpgradable(r) || isModified(r);
    return true;
  });
  const sourceLabel = (id: string) => {
    const s = sources.find((x) => x.id === id);
    return s ? sourceName(t, s) : id;
  };

  return (
    <section>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-[16px] font-semibold">{t("settings.tab.skills")}</h2>
          <p className="text-[13px] text-muted mt-1 leading-relaxed">{t("skills.subtitle")}</p>
        </div>
        {/* One add-action, three doors behind it (SKILLS-SPEC §5): the list is the page. */}
        <div className="relative shrink-0">
          <button
            className={BTN_ACCENT}
            aria-haspopup="menu"
            aria-expanded={addOpen}
            onClick={() => setAddOpen((v) => !v)}
          >
            <span className="inline-flex items-center gap-1.5">
              <Icon name="plus" size={13} /> {t("skills.add_skill")}
            </span>
          </button>
          {addOpen ? (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setAddOpen(false)} />
              <div
                role="menu"
                className="absolute right-0 top-full mt-1.5 w-80 rounded-xl2 border border-line bg-panel shadow-xl z-20 p-1.5"
                onKeyDown={(e) => e.key === "Escape" && !isComposing(e) && setAddOpen(false)}
              >
                <button
                  role="menuitem"
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-paper"
                  onClick={() => {
                    setAddOpen(false);
                    setEditor(emptyEditor());
                  }}
                >
                  <div className="text-[13px] font-medium">{t("skills.door_write")}</div>
                  <div className="text-[12px] text-muted">{t("skills.door_write_sub")}</div>
                </button>
                <button
                  role="menuitem"
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-paper"
                  onClick={() => {
                    setAddOpen(false);
                    fileInput.current?.click();
                  }}
                >
                  <div className="text-[13px] font-medium">{t("skills.door_import")}</div>
                  <div className="text-[12px] text-muted">{t("skills.door_import_sub")}</div>
                </button>
                {isTauri() && (
                  <button
                    role="menuitem"
                    className="w-full text-left px-3 py-2 rounded-lg hover:bg-paper"
                    data-testid="import-folder"
                    onClick={() => {
                      setAddOpen(false);
                      void onPickFolder();
                    }}
                  >
                    <div className="text-[13px] font-medium">{t("Import a folder")}</div>
                    <div className="text-[11.5px] text-muted">
                      {t("A skill folder on this computer — no zipping, build files are left out")}
                    </div>
                  </button>
                )}
                <button
                  role="menuitem"
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-paper disabled:opacity-40"
                  disabled={!onCreateSkill}
                  onClick={() => {
                    setAddOpen(false);
                    onCreateSkill?.("");
                  }}
                >
                  <div className="text-[13px] font-medium">{t("skills.door_ai")}</div>
                  <div className="text-[12px] text-muted">{t("skills.door_ai_sub")}</div>
                </button>
              </div>
            </>
          ) : null}
        </div>
      </div>
      <input
        ref={fileInput}
        type="file"
        accept=".zip,.md"
        className="hidden"
        aria-label={t("skills.upload_aria")}
        onChange={(e) => {
          onPickFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      {error ? (
        <div className="text-[13px] text-red-500 mb-3" role="alert">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div
          role="status"
          className={
            "mb-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-[13px] " +
            (notice.tone === "ok"
              ? "bg-tealSoft/70 text-tealInk border-tealInk/20"
              : "bg-warnSoft/70 text-warnInk border-warnInk/20")
          }
        >
          <span className="min-w-0">
            <b>{notice.name}</b> {notice.text}
          </span>
          <IconButton
            variant="inline"
            icon="x"
            size={12}
            className="ml-auto opacity-60 hover:opacity-100"
            label={t("common.dismiss")}
            onClick={() => setNotice(null)}
          />
        </div>
      ) : null}

      {sources.length ? (
        <SkillSourcesPanel
          sources={sources}
          onChanged={(next) => {
            setSources(next);
            setError("");
            refresh();
          }}
          onError={setError}
        />
      ) : null}

      {confirmModified ? (
        <div className={`${CARD} p-4 mb-4`} role="alertdialog" data-testid="confirm-modified">
          <div className="text-[13px] font-medium mb-1">{t("skills.confirm_modified_title")}</div>
          <p className="text-[13px] text-muted mb-2">{t("skills.confirm_modified_sub")}</p>
          <ul className="text-[12.5px] mb-3 space-y-1">
            {confirmModified.map((r) => (
              <li key={rowKey(r)}>
                <b>{r.name}</b>
                {r.update?.changes?.length ? (
                  <span className="text-muted">
                    {" — "}
                    {r.update.changes.slice(0, 4).join("、")}
                    {(r.update.changes_count ?? 0) > 4
                      ? t("skills.more_changes", { count: (r.update.changes_count ?? 0) - 4 })
                      : ""}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <button className={BTN_ACCENT} onClick={() => void upgrade(true)}>
              {t("skills.confirm_modified_go")}
            </button>
            <button className={BTN_BORDERED} onClick={() => setConfirmModified(null)}>
              {t("folder_gate.cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {results ? (
        <div className={`${CARD} p-4 mb-4`} data-testid="upgrade-results">
          <div className="flex items-center mb-2">
            <div className="text-[13px] font-medium">{t("skills.results_title")}</div>
            <IconButton
              variant="inline"
              icon="x"
              size={12}
              className="ml-auto opacity-60 hover:opacity-100"
              label={t("common.dismiss")}
              onClick={() => setResults(null)}
            />
          </div>
          <ul className="text-[12.5px] space-y-1.5">
            {results.map((r) => (
              <li key={`${r.origin}:${r.name}`}>
                <b>{r.name}</b>{" "}
                {r.ok ? (
                  <span className="text-tealInk">
                    {r.unchanged ? t("skills.result_unchanged") : t("skills.result_ok")}
                  </span>
                ) : (
                  <span className="text-red-500">{r.error || t("skills.error_generic")}</span>
                )}
                {r.warning ? <div className="text-warnInk">{r.warning}</div> : null}
                {r.copies?.length ? (
                  <div className="text-muted">{t("skills.result_copies", { items: r.copies.join("、") })}</div>
                ) : null}
                {r.kept?.length ? <div className="text-muted">{r.kept.join("；")}</div> : null}
                {r.skipped?.length ? (
                  <div className="text-muted">
                    {t("skills.excluded_automatically", { items: r.skipped.join(", ") })}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {upload ? (
        <div className={`${CARD} p-4 mb-4`}>
          <div className="text-[13px] font-medium mb-1">{t("skills.review_title")}</div>
          <p className="text-[13px] text-muted mb-3">{t("skills.review_sub")}</p>
          <div className="text-[13px] mb-1">
            <span className="font-medium">{upload.name}</span>
            <span className="text-muted"> — {upload.description || t("skills.no_description")}</span>
          </div>
          <pre className="text-[12px] bg-paper border border-line rounded-lg p-3 whitespace-pre-wrap max-h-64 overflow-y-auto mb-2">
            {upload.instructions}
          </pre>
          {upload.files?.length ? (
            <div className="text-[12px] text-muted mb-2">
              {t("skills.bundled_files", { files: upload.files.join(", ") })}
            </div>
          ) : null}
          {/* The import filter is automatic but never silent: a user told nothing was dropped
              can end up sure they installed something they did not. Fork-only — upstream has
              no import hygiene gate, so the merge removed this and left the test asserting it. */}
          {upload.skipped?.length ? (
            <div className="text-[12px] text-muted mb-2" data-testid="upload-skipped">
              {t("skills.excluded_automatically", { items: upload.skipped.join(", ") })}
            </div>
          ) : null}
          <div className="flex gap-2 mt-3">
            <button className={BTN_ACCENT} onClick={confirmUpload}>
              {t("skills.install_skill")}
            </button>
            <button className={BTN_BORDERED} onClick={() => setUpload(null)}>
              {t("folder_gate.cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {editor ? (
        <div className={`${CARD} p-4 mb-4`}>
          <div className="text-[13px] font-medium mb-3">
            {editor.mode === "new"
              ? t("skills.editor_new")
              : t("skills.editor_edit", { name: editor.name })}
          </div>
          <label className={FIELD_LABEL} htmlFor="skill-name">
            {t("skills.name_label")}
          </label>
          <input
            id="skill-name"
            className={`${INPUT} mt-1 mb-3`}
            value={editor.name}
            disabled={editor.mode === "edit"}
            placeholder={t("skills.name_placeholder")}
            onChange={(e) => setEditor({ ...editor, name: e.target.value })}
          />
          <label className={FIELD_LABEL} htmlFor="skill-desc">
            {t("skills.desc_label")}
          </label>
          <input
            id="skill-desc"
            className={`${INPUT} mt-1 mb-3`}
            value={editor.description}
            placeholder={t("skills.desc_placeholder")}
            onChange={(e) => setEditor({ ...editor, description: e.target.value })}
          />
          <label className={FIELD_LABEL} htmlFor="skill-instructions">
            {t("skills.instructions_label")}
          </label>
          <textarea
            id="skill-instructions"
            className={`${INPUT} mt-1 mb-3 min-h-[140px] font-mono`}
            value={editor.instructions}
            placeholder={t("skills.instructions_placeholder")}
            onChange={(e) => setEditor({ ...editor, instructions: e.target.value })}
          />
          <div className="flex gap-2 mt-3">
            <button
              className={BTN_ACCENT}
              disabled={!editor.name.trim() || !editor.instructions.trim()}
              onClick={save}
            >
              {t("skills.save_skill")}
            </button>
            <button className={BTN_BORDERED} onClick={() => setEditor(null)}>
              {t("folder_gate.cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {rows.length ? (
        <div className="flex flex-wrap items-center gap-2 mb-2" data-testid="skills-toolbar">
          <div className="inline-flex rounded-lg border border-line bg-paper p-0.5" role="tablist">
            {(
              [
                ["all", t("skills.filter_all")],
                ["own", t("skills.filter_own")],
                ...(hasExternal ? [["external", t("skills.filter_external")]] : []),
                ["updates", t("skills.filter_updates", { count: upgradableCount })],
              ] as [Filter, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={filter === key}
                className={
                  "px-2.5 py-1 rounded-md text-[12px] " +
                  (filter === key ? "bg-panel text-ink font-medium shadow-sm" : "text-muted hover:text-ink")
                }
                onClick={() => setFilter(key)}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="ml-auto text-[12px] text-faint">{formatChecked(t, checkedAt)}</span>
          <button
            className={BTN_BORDERED}
            disabled={checking}
            onClick={() => void runCheck()}
            data-testid="check-updates"
          >
            <span className="inline-flex items-center gap-1.5">
              <Icon name="refresh" size={12} /> {checking ? t("skills.checking") : t("skills.check_updates")}
            </span>
          </button>
        </div>
      ) : null}

      <div className={`${CARD} divide-y divide-line`}>
        {loadFailed && rows.length === 0 && !editor ? (
          <div className="p-5 text-[13px] text-muted">
            <div>{t("skills.load_failed")}</div>
            <button className={BTN_BORDERED + " mt-2"} onClick={refresh} data-testid="skills-retry">
              {t("common.retry")}
            </button>
          </div>
        ) : rows.length === 0 && !editor ? (
          <div className="p-5 text-[13px] text-muted">
            <Trans i18nKey="skills.empty" components={{ b: <b /> }} />
          </div>
        ) : null}
        {rows.length > 0 && visibleRows.length === 0 ? (
          <div className="p-5 text-[13px] text-muted">{t("skills.filter_empty")}</div>
        ) : null}
        {visibleRows.map((row) => {
          const external = row.origin === "external";
          const chip = statusChip(t, row);
          const upgradable = isUpgradable(row);
          return (
          <div key={rowKey(row)} className="flex items-center gap-3 px-4 py-3" data-testid={`skill-row-${rowKey(row)}`}>
            {upgradable ? (
              <input
                type="checkbox"
                className="shrink-0 accent-accent"
                checked={selected.has(rowKey(row))}
                aria-label={t("skills.select_aria", { name: row.name })}
                onChange={(e) => toggleSelected(row, e.target.checked)}
              />
            ) : null}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[13px] font-medium ${row.enabled ? "" : "text-muted"}`}>
                  {row.name}
                </span>
                {external ? (
                  <span
                    className={BADGE}
                    title={
                      row.also_in?.length
                        ? t("skills.also_in", { items: row.also_in.map(sourceLabel).join("、") })
                        : undefined
                    }
                  >
                    {row.source_id ? sourceLabel(row.source_id) : row.source_label}
                  </span>
                ) : row.origin === "library" ? (
                  <span className={BADGE}>{t("skills.origin_library")}</span>
                ) : row.source !== "local" ? (
                  <span className={BADGE}>{row.source}</span>
                ) : null}
                {external ? (
                  <span className={BADGE} title={t("skills.read_only_tip")}>
                    {t("skills.read_only")}
                  </span>
                ) : null}
                {row.shadowed_by ? (
                  <span className={BADGE} title={t("skills.shadowed_tip")}>
                    {t("skills.shadowed")}
                  </span>
                ) : null}
                {chip ? (
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded-full border shrink-0 ${CHIP_TONE[chip.tone]}`}
                    title={chip.title}
                    data-testid="update-status"
                  >
                    {chip.text}
                  </span>
                ) : null}
                {/* §6: a rich skill must not look identical to a one-file one. Styled as a
                    chip with a folder icon so it READS as clickable (live drive: plain
                    text hid the affordance). */}
                {row.files ? (
                  <button
                    className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-md border border-line bg-paper text-muted hover:text-ink hover:border-lineStrong shrink-0"
                    title={t("skills.show_folder")}
                    onClick={() => revealSkill(row.name)}
                  >
                    <Icon name="folder" size={11} /> {t("skills.file_count", { count: row.files })}
                  </button>
                ) : null}
              </div>
              {/* Full description, wrapping — a skill's one-liner is its menu entry; cutting
                  it mid-word hid what the skill does (live drive). */}
              <div className="text-[12px] text-muted leading-relaxed">{row.description}</div>
              {isModified(row) && row.update?.changes?.length ? (
                <div className="text-[11.5px] text-warnInk leading-relaxed mt-0.5">
                  {t("skills.local_changes", { items: row.update.changes.slice(0, 3).join("、") })}
                  {(row.update.changes_count ?? 0) > 3
                    ? t("skills.more_changes", { count: (row.update.changes_count ?? 0) - 3 })
                    : ""}
                </div>
              ) : null}
            </div>
            {row.can_rollback ? (
              <button
                className={BTN_BORDERED + " text-[12px]"}
                title={t("skills.rollback_tip")}
                onClick={() => void rollback(row)}
              >
                {t("skills.rollback")}
              </button>
            ) : null}
            {/* 来源与升级 §3: external skills are manual by default — out of the per-turn
                catalog, loaded only when picked with "/". The author's
                disable-model-invocation locks it. */}
            {external ? (
              row.invocation_locked ? (
                <span className={BADGE} title={t("skills.invocation_locked_tip")}>
                  {t("skills.manual_badge")}
                </span>
              ) : (
                <div
                  className="inline-flex rounded-lg border border-line bg-paper p-0.5 shrink-0"
                  role="radiogroup"
                  aria-label={t("skills.invocation_aria", { name: row.name })}
                >
                  {(["manual", "auto"] as const).map((mode) => (
                    <button
                      key={mode}
                      role="radio"
                      aria-checked={(row.invocation ?? "manual") === mode}
                      title={mode === "auto" ? t("skills.auto_tip") : t("skills.manual_tip")}
                      className={
                        "px-2 py-0.5 rounded-md text-[11.5px] " +
                        ((row.invocation ?? "manual") === mode
                          ? "bg-panel text-ink font-medium shadow-sm"
                          : "text-muted hover:text-ink")
                      }
                      onClick={() =>
                        (row.invocation ?? "manual") !== mode && void setInvocation(row, mode)
                      }
                    >
                      {mode === "auto" ? t("skills.auto_badge") : t("skills.manual_badge")}
                    </button>
                  ))}
                </div>
              )
            ) : null}
            {/* Row actions: the shared IconButton (tooltip + accessible name from one `label`)
                and the shared Toggle, so this row matches the persona page and the rail.
                External skills are another tool's files: no edit, no delete (来源与升级 §1). */}
            {external ? null : (
            <IconButton
              variant="bordered"
              icon="pencil"
              size={13}
              label={t("skills.edit_tip")}
              onClick={() =>
                setEditor({
                  mode: "edit",
                  name: row.name,
                  description: row.description,
                  instructions: row.instructions,
                })
              }
            />
            )}
            {external ? null : armedDelete === row.name ? (
              /* Armed: the same slot turns into a text button so the second click is informed.
                 autoFocus keeps focus on the slot for keyboard users; tabbing away disarms
                 (relatedTarget is the next stop). A blur with no relatedTarget is WebKit
                 dropping focus on mousedown — the effect above owns pointer disarming. */
              <button
                className={BTN_BORDERED + " text-danger"}
                autoFocus
                data-confirm-delete
                aria-label={t("skills.delete_aria", { name: row.name })}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => remove(row)}
                onBlur={(e) => e.relatedTarget && setArmedDelete(null)}
              >
                {t("skills.confirm_delete")}
              </button>
            ) : (
              <IconButton
                variant="bordered"
                tone="danger"
                icon="trash"
                size={13}
                label={t("skills.delete_aria", { name: row.name })}
                onClick={() => remove(row)}
              />
            )}
            <Toggle
              checked={row.enabled}
              label={t("skills.enabled_aria", { name: row.name })}
              onChange={(on) => {
                updateSkill(row.name, { enabled: on }).then((res) => {
                  if (!fail(res))
                    setNotice({
                      name: row.name,
                      text: on ? CONFIRMATION : OFF_NOTE,
                      tone: on ? "ok" : "warn",
                    });
                  refresh();
                });
              }}
            />
          </div>
          );
        })}
      </div>

      {/* The batch bar (来源与升级 §7): sticks to the bottom of the scrolling settings page
          while anything is ticked. */}
      {selectedRows.length ? (
        <div
          className="sticky bottom-0 mt-3 flex items-center gap-3 rounded-xl2 border border-line bg-panel px-4 py-2.5 shadow-lg"
          data-testid="upgrade-bar"
        >
          <span className="text-[13px]">{t("skills.selected_count", { count: selectedRows.length })}</span>
          <button className={BTN_BORDERED + " ml-auto"} onClick={() => setSelected(new Set())}>
            {t("skills.clear_selection")}
          </button>
          <button className={BTN_ACCENT} disabled={applying} onClick={() => void upgrade(false)}>
            {applying ? t("skills.upgrading") : t("skills.upgrade_selected")}
          </button>
        </div>
      ) : null}
    </section>
  );
}
