import { useState } from "react";
import { useTranslation } from "react-i18next";
import { addSkillSource, removeSkillSource, setSkillSource, type SkillSource } from "../api";
import { chooseFolder, isTauri } from "../tauri";
import { BTN_BORDERED } from "./buttons";
import { Icon } from "./Icon";
import { IconButton } from "./IconButton";
import { Toggle } from "./Toggle";

// 来源与升级 §1 — the skill folders other agent tools keep under the home folder. Every one
// starts OFF: switching a source on is the person's decision, and the count next to each
// says what it would bring in. External skills are read in place and stay read-only here.

const INPUT =
  "w-full min-w-0 px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";

export function sourceName(t: (k: string, o?: Record<string, unknown>) => string, s: { id: string; label: string }) {
  return t(`skills.source_name.${s.id}`, { defaultValue: s.label });
}

export function SkillSourcesPanel({
  sources,
  onChanged,
  onError,
}: {
  sources: SkillSource[];
  /** Fresh list from the server after a change; the parent also reloads the skills. */
  onChanged: (sources: SkillSource[]) => void;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation();
  const anyOn = sources.some((s) => s.enabled);
  const detected = sources.filter((s) => s.exists && s.count > 0).length;
  const [open, setOpen] = useState(!anyOn);
  const [typing, setTyping] = useState(false);
  const [path, setPath] = useState("");

  const done = (res: { ok: boolean; error?: string; sources?: SkillSource[] }) => {
    if (res.ok === false) {
      onError(res.error || t("skills.error_generic"));
      return false;
    }
    if (res.sources) onChanged(res.sources);
    return true;
  };

  const add = async (folder: string) => {
    if (!folder.trim()) return;
    if (done(await addSkillSource(folder.trim()))) {
      setPath("");
      setTyping(false);
    }
  };

  const onAdd = async () => {
    if (isTauri()) {
      const picked = await chooseFolder();
      if (picked) await add(picked);
      return;
    }
    setTyping(true);
  };

  return (
    <div className="rounded-xl2 border border-line bg-panel mb-4" data-testid="skill-sources">
      <button
        className="w-full flex items-center gap-2 px-4 py-3 text-left"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name={open ? "chevronDown" : "chevronRight"} size={13} />
        <span className="text-[13px] font-medium">{t("skills.sources_title")}</span>
        <span className="text-[12px] text-muted">
          {t("skills.sources_summary", {
            on: sources.filter((s) => s.enabled).length,
            found: detected,
          })}
        </span>
      </button>
      {open ? (
        <div className="px-4 pb-3">
          <p className="text-[12px] text-muted leading-relaxed mb-2">{t("skills.sources_sub")}</p>
          <div className="divide-y divide-line border border-line rounded-lg bg-paper">
            {sources.map((s) => (
              <div key={s.id} className="flex items-center gap-3 px-3 py-2" data-testid={`source-${s.id}`}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-[13px] font-medium ${s.exists ? "" : "text-muted"}`}>
                      {sourceName(t, s)}
                    </span>
                    <span className="text-[11px] text-muted shrink-0">
                      {s.exists ? t("skills.source_count", { count: s.count }) : t("skills.source_missing")}
                    </span>
                  </div>
                  <div className="text-[11.5px] text-faint font-mono truncate" title={s.path}>
                    {s.path}
                  </div>
                </div>
                {s.custom ? (
                  <IconButton
                    variant="bordered"
                    tone="danger"
                    icon="trash"
                    size={12}
                    label={t("skills.source_remove", { name: sourceName(t, s) })}
                    onClick={async () => done(await removeSkillSource(s.id))}
                  />
                ) : null}
                <Toggle
                  checked={s.enabled}
                  disabled={!s.exists && !s.enabled}
                  label={t("skills.source_toggle", { name: sourceName(t, s) })}
                  onChange={async (on) => done(await setSkillSource(s.id, on))}
                />
              </div>
            ))}
          </div>
          {typing ? (
            <div className="flex gap-2 mt-2">
              <input
                className={INPUT}
                autoFocus
                value={path}
                placeholder={t("skills.source_path_placeholder")}
                aria-label={t("skills.source_path_placeholder")}
                onChange={(e) => setPath(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void add(path)}
              />
              <button className={BTN_BORDERED} onClick={() => void add(path)}>
                {t("skills.source_add_confirm")}
              </button>
              <button className={BTN_BORDERED} onClick={() => setTyping(false)}>
                {t("folder_gate.cancel")}
              </button>
            </div>
          ) : (
            <button className={BTN_BORDERED + " mt-2"} onClick={() => void onAdd()}>
              <span className="inline-flex items-center gap-1.5">
                <Icon name="folderPlus" size={13} /> {t("skills.source_add")}
              </span>
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}
