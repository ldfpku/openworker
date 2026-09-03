import { isComposing } from "../ime";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { addModel, getSettings, removeModel, setDefaultModel, type ProviderCatalog } from "../api";
import { isFreeModel } from "../providers/logos";
import { formatRelative } from "../relTime";
import { BTN_ACCENT_SM } from "./buttons";

// Cloud-account providers dispatch by a family segment baked into the model id
// (`bedrock:claude/…`, `vertex:openweight/…`). The add-model row shows a dropdown so
// users pick the family instead of memorizing the prefix; curated matrix ids already
// carry theirs.
const MODEL_FAMILIES: Record<string, { value: string; label: string }[]> = {
  bedrock: [
    { value: "claude", label: "Claude family" },
    { value: "other", label: "Other models" },
  ],
  vertex: [
    { value: "gemini", label: "Gemini family" },
    { value: "claude", label: "Claude family" },
    { value: "openweight", label: "Open-weight" },
  ],
};

// One provider's models as a checklist: tick = shown in the composer's model picker (the
// curated list), the black "default" badge marks the model new sessions use, and hovering any
// other row reveals "Make default". A free-type row below adds models by hand, so brand-new
// releases work without an app update. Shared by Onboarding and Manage → Configure Models.
export function ModelChecklist({
  provider,
  knownProviders,
  suggested,
  curated,
  defaultModel,
  labels,
  catalog,
  onRefresh,
  onChanged,
}: {
  provider: string; // decides the id prefix; OpenAI models stay bare
  knownProviders: string[]; // all provider names, to parse prefixes in curated ids
  suggested: string[]; // bare model names suggested by the provider
  curated: string[]; // the full curated list (all providers, full ids)
  defaultModel: string;
  labels?: Record<string, string>; // curated display names (full id → label); raw id when absent
  catalog?: ProviderCatalog; // live model-catalog status; absent on old servers
  onRefresh?: () => Promise<void>; // re-fetch this provider's live catalog
  onChanged: (next: { models: string[]; model: string }) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const families = MODEL_FAMILIES[provider];
  const [family, setFamily] = useState(families?.[0]?.value || "");

  const provOf = (id: string) => {
    const i = id.indexOf(":");
    return i > 0 && knownProviders.includes(id.slice(0, i)) ? id.slice(0, i) : "openai";
  };
  const prefixed = (m: string) => (provider === "openai" || provOf(m) !== "openai" ? m : `${provider}:${m}`);
  const bare = (id: string) => (id.startsWith(`${provider}:`) ? id.slice(provider.length + 1) : id);

  const rows = [
    ...suggested.map(prefixed),
    ...curated.filter((id) => provOf(id) === provider),
  ].filter((id, i, a) => a.indexOf(id) === i);

  // Once the list comes live from the provider's real API, a text filter beats scrolling
  // through it — but only once it's long enough to need one.
  const showFilter = !!catalog?.live && rows.length > 12;
  const needle = filter.trim().toLowerCase();
  const visibleRows =
    showFilter && needle
      ? rows.filter((id) => id.toLowerCase().includes(needle) || (labels?.[id] || "").toLowerCase().includes(needle))
      : rows;

  const checked = (id: string) => curated.includes(id);
  const refresh = async () => {
    const s = await getSettings();
    onChanged({ models: s.models, model: s.model });
  };
  const doRefresh = async () => {
    if (!onRefresh || refreshing) return;
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setRefreshing(false);
    }
  };

  const tick = async (id: string, on: boolean) => {
    const res = on ? await addModel(id) : await removeModel(id);
    if (res.ok) onChanged({ models: res.models, model: res.model });
  };
  const makeDefault = async (id: string) => {
    if (!checked(id)) await addModel(id); // defaulting an unticked row ticks it too
    await setDefaultModel(id);
    await refresh();
  };
  const add = async () => {
    let typed = draft.trim();
    if (!typed) return;
    // Fold the family choice into the id unless the user already typed one.
    if (families && !families.some((f) => typed.startsWith(`${f.value}/`))) {
      typed = `${family}/${typed}`;
    }
    const res = await addModel(prefixed(typed));
    if (res.ok) {
      setDraft("");
      onChanged({ models: res.models, model: res.model });
    }
  };

  return (
    <div className="mlist">
      {catalog?.live && (
        <div className="text-[12px] text-muted mb-1.5 flex items-center gap-2">
          <span>
            {t("models.catalog_live", { when: formatRelative(catalog.fetched_at, t, { style: "short" }) })}
          </span>
          <button
            className="text-[12px] px-2 py-0.5 rounded-md border border-line bg-paper hover:border-lineStrong shrink-0 disabled:opacity-50"
            onClick={doRefresh}
            disabled={refreshing}
          >
            {refreshing ? t("models.catalog_refreshing") : t("models.catalog_refresh")}
          </button>
        </div>
      )}
      {catalog && !catalog.live && catalog.error && (
        <div className="text-[12px] text-muted mb-1.5 flex items-center gap-2">
          <span>{t("models.catalog_error", { error: catalog.error })}</span>
          <button
            className="text-[12px] px-2 py-0.5 rounded-md border border-line bg-paper hover:border-lineStrong shrink-0 disabled:opacity-50"
            onClick={doRefresh}
            disabled={refreshing}
          >
            {refreshing ? t("models.catalog_refreshing") : t("models.catalog_retry")}
          </button>
        </div>
      )}
      {catalog && !catalog.supported && (
        <div className="text-[12px] text-muted mb-1.5">{t("models.catalog_unsupported")}</div>
      )}
      {showFilter && (
        <input
          className="w-full bg-paper border border-lineStrong rounded-lg px-2.5 py-1.5 text-[13px] outline-none focus:border-accent mb-1.5"
          placeholder={t("models.filter_placeholder")}
          value={filter}
          spellCheck={false}
          autoComplete="off"
          onChange={(e) => setFilter(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !isComposing(e) && e.preventDefault()}
        />
      )}
      {visibleRows.map((id) => {
        const isDefault = id === defaultModel;
        return (
          <div className={"mlist-row" + (checked(id) ? "" : " off")} key={id}>
            <label className="mlist-main">
              <input
                type="checkbox"
                checked={checked(id)}
                disabled={isDefault}
                title={isDefault ? t("models.default_locked") : undefined}
                onChange={(e) => tick(id, e.target.checked)}
              />
              <span className="mlist-name" title={id}>
                {labels?.[id] || bare(id)}
              </span>
              {isFreeModel(id) && (
                <span
                  className="mlist-free"
                  title={t("Runs on the company NVIDIA relay or your own machine — no model bill")}
                >
                  {t("Free")}
                </span>
              )}
            </label>
            {isDefault ? (
              <span className="mlist-default">{t("models.default_badge")}</span>
            ) : (
              <button className="mlist-make" onClick={() => makeDefault(id)}>
                {t("models.make_default")}
              </button>
            )}
          </div>
        );
      })}
      {!catalog?.live && (
        <div className="mlist-add">
          {families && (
            <select
              value={family}
              onChange={(e) => setFamily(e.target.value)}
              aria-label={t("Model family")}
              data-testid="mlist-family"
            >
              {families.map((f) => (
                <option key={f.value} value={f.value}>
                  {t(f.label)}
                </option>
              ))}
            </select>
          )}
          <input
            placeholder={t("models.add_placeholder")}
            value={draft}
            spellCheck={false}
            autoComplete="off"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !isComposing(e) && add()}
          />
          <button className={BTN_ACCENT_SM} onClick={add} disabled={!draft.trim()}>
            {t("models.add_btn")}
          </button>
        </div>
      )}
    </div>
  );
}
