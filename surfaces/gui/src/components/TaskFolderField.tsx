import { useState } from "react";
import { useTranslation } from "react-i18next";
import { getRecentWorkspaces, type RecentWorkspace } from "../api";
import { chooseFolder } from "../tauri";
import { baseName } from "../paths";
import { Icon } from "./Icon";

// The automation "workspace" picker (used by the new-automation form, each quickstart
// template's config card, and the task detail's edit mode): a button + menu, NOT a native
// <select> — ScheduledView.test.tsx locates the schedule "Repeat" dropdown with
// getByRole("combobox"), and a second combobox on the page would break that lookup.
//
// The menu mirrors SessionSetupRow's recent-folders + browse pattern (that component is
// per-SESSION and stays untouched here — this one is per-AUTOMATION and has its own, simpler
// "back to the private folder" option instead of a folder-required gate).
interface Props {
  value: string; // "" = the automation's own private, empty folder
  onChange: (v: string) => void;
  required?: boolean;
}

export function TaskFolderField({ value, onChange, required }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [recents, setRecents] = useState<RecentWorkspace[] | null>(null);

  const toggle = () => {
    if (!open) getRecentWorkspaces().then(setRecents).catch(() => setRecents([]));
    setOpen((v) => !v);
  };

  const pick = (path: string) => {
    onChange(path);
    setOpen(false);
  };

  // chooseFolder() returns null on cancel (or when no picker is available) — leave the
  // current value alone and keep the menu open so the user can try another option.
  const browse = async () => {
    const picked = await chooseFolder();
    if (picked) pick(picked);
  };

  const currentLabel = value ? baseName(value) : t("automations.folder_private");

  return (
    <div className="mt-3" data-testid="task-folder-field">
      <label className="block text-[12px] text-muted mb-1">{t("automations.folder_label")}</label>
      <div className="relative">
        <button
          type="button"
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg border border-line bg-panel text-[13px] outline-none hover:border-lineStrong focus:border-accent"
          onClick={toggle}
          aria-required={required || undefined}
          data-testid="task-folder-trigger"
        >
          <Icon name="folder" size={13} className="text-muted shrink-0" />
          <span className="min-w-0 flex-1 text-left truncate" title={value || undefined}>
            {currentLabel}
          </span>
          <Icon name="chevronDown" size={12} className="text-faint shrink-0" />
        </button>
        {open && (
          <>
            <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
            <div
              className="absolute top-full mt-1 left-0 z-30 w-[300px] bg-panel border border-line rounded-xl2 shadow-xl p-1"
              data-testid="task-folder-menu"
            >
              <button
                className={
                  "w-full text-left px-2.5 py-2 rounded-lg hover:bg-paper text-[13px] " +
                  (!value ? "bg-accentSoft/50" : "")
                }
                onClick={() => pick("")}
                data-testid="task-folder-private-option"
              >
                {t("automations.folder_option_private")}
              </button>
              {(recents || [])
                .filter((w) => w.exists)
                .slice(0, 5)
                .map((w) => (
                  <button
                    key={w.path}
                    className={
                      "w-full text-left flex items-start gap-2.5 px-2.5 py-2 rounded-lg hover:bg-paper " +
                      (value === w.path ? "bg-accentSoft/50" : "")
                    }
                    onClick={() => pick(w.path)}
                    title={w.path}
                    data-testid={`task-folder-recent-${w.path}`}
                  >
                    <Icon name="folder" size={13} className="mt-0.5 shrink-0 text-muted" />
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium text-ink truncate">{baseName(w.path)}</span>
                      <span className="block text-[12px] text-faint truncate">{w.path}</span>
                    </span>
                  </button>
                ))}
              <div className="border-t border-line mt-1 pt-1">
                <button
                  className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-paper text-[12px] text-accent"
                  onClick={() => void browse()}
                  data-testid="task-folder-browse"
                >
                  {t("automations.folder_browse")}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
      <p className="text-[11px] text-faint mt-1">{t("automations.folder_hint")}</p>
    </div>
  );
}
