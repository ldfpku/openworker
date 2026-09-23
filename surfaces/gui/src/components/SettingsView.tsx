import { isComposing } from "../ime";
import { useEffect, useState } from "react";
import { getI18n, Trans, useTranslation } from "react-i18next";
import { getStoredLanguage, setLanguage as setI18nLanguage, type Lang } from "../i18n";
import {
  getSettings,
  getTrustedWorkspaces,
  setAutoApprove,
  setAutoApproveShadow,
  setCompactionSettings,
  setContextBar,
  setOnboarded,
  setPdfSettings,
  setScratchBase,
  setSessionsPeek,
  setWorkspaceTrusted,
  type CompactionSettings,
  type ModelSettings,
  type PdfSettings,
  type WorkspaceCommandTrust,
} from "../api";
import {
  cancelDictationModelDownload,
  cleanupLegacyDictationModels,
  deleteDictationModel,
  downloadDictationModel,
  getAutostart,
  getDictationStatus,
  getKeepAwake,
  checkForUpdate,
  installUpdate,
  isTauri,
  listenDictationDownloadProgress,
  markDictationTestPassed,
  pickFolder,
  setAutostart,
  setKeepAwake,
  startDictation,
  stopDictation,
  verifyDictationModel,
  type DictationDownloadProgress,
  type DictationPack,
  type DictationStatus,
} from "../tauri";
import { useThemePref } from "../theme";
import { BTN_ACCENT, BTN_BORDERED } from "./buttons";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";
import { ModelsTab } from "./ManageTabs";
import { MemorySection } from "./MemorySection";
import { sortModelIds } from "../modelOrder";
import { PersonasTab } from "./PersonasTab";
import { SkillsTab } from "./SkillsTab";
import { showPersonas } from "../flags";

// Settings, restructured (Option 2) into a full-page surface that mirrors IntegrationsView's shell:
// a left sub-nav (Appearance · Files · Models · Personas) + centered panel, replacing the old
// top-tab ManageModal. Local/app concerns live here; anything external (Connectors, Messaging, MCP,
// Activity) stays under Integrations. Appearance + Files are re-skinned to the mock's Tailwind idiom;
// Models + Personas host the existing tab components inside the page shell (field re-skin to follow).
// "appearance" is the General tab's stable key — callers deep-link with it, so the
// rename (UX-021) changed only the label. "files" folded into General as a card.
type SetTab = "appearance" | "models" | "context" | "skills" | "voice" | "memory" | "personas";

const CARD = "rounded-xl2 border border-line bg-panel";
const FIELD_LABEL = "text-[13px] font-medium text-ink";
const FIELD_HELP = "text-[12px] text-muted mt-1.5 leading-relaxed";
const INPUT =
  "flex-1 min-w-0 px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";

const SET_TABS: {
  key: SetTab;
  labelKey: string;
  icon: "sliders" | "code" | "mic" | "archive" | "sparkle" | "book" | "refresh";
}[] = [
  { key: "appearance", labelKey: "settings.tab.general", icon: "sliders" },
  { key: "models", labelKey: "settings.tab.models", icon: "code" },
  { key: "context", labelKey: "settings.tab.context", icon: "refresh" },
  { key: "skills", labelKey: "settings.tab.skills", icon: "book" },
  { key: "voice", labelKey: "settings.tab.voice", icon: "mic" },
  { key: "memory", labelKey: "settings.tab.memory", icon: "archive" },
  { key: "personas", labelKey: "settings.tab.personas", icon: "sparkle" },
];

export function SettingsView({
  initialTab,
  onOpenPersona,
  onCreateSkill,
}: {
  initialTab?: SetTab;
  onOpenPersona?: (id: string) => void;
  // Skills doorway (SKILLS-SPEC §5.2): start a new conversation with the description
  // prefilled — the worker builds the skill and proposes it via save_skill.
  onCreateSkill?: (description: string) => void;
}) {
  const { t } = useTranslation();
  // Personas is flag-gated (hidden for launch) — filter the tab AND coerce a stale
  // deep-link to it (openSettings("personas") callers) so the page never opens on a
  // section with no nav entry.
  const personas = showPersonas();
  const tabs = personas ? SET_TABS : SET_TABS.filter((tab) => tab.key !== "personas");
  const wanted = initialTab && (personas || initialTab !== "personas") ? initialTab : "appearance";
  const [tab, setTab] = useState<SetTab>(wanted);

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <nav className="page-subnav w-[208px] shrink-0 border-r border-line bg-panel/40 px-3 py-4">
        <div className="px-2 text-[13px] font-semibold mb-3 flex items-center gap-2">
          <Icon name="gear" size={16} /> {t("nav.settings")}
        </div>
        {tabs.map((tb) => {
          const active = tab === tb.key;
          return (
            <button
              key={tb.key}
              className={
                "w-full text-left px-2.5 py-2 rounded-lg text-[13px] flex items-center gap-2 " +
                (active ? "bg-paper text-accent font-medium" : "text-muted hover:bg-paper hover:text-ink")
              }
              onClick={() => setTab(tb.key)}
            >
              <Icon name={tb.icon} size={15} /> {t(tb.labelKey)}
            </button>
          );
        })}
      </nav>

      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-3xl mx-auto px-7 py-6">
          {tab === "appearance" ? (
            <AppearanceSection />
          ) : tab === "models" ? (
            <section>
              <PanelHead
                title={t("settings.tab.models")}
                sub={t("settings.models_sub")}
              />
              <ModelsTab />
            </section>
          ) : tab === "context" ? (
            <section>
              <PanelHead
                title={t("Context optimization")}
                sub={t("How sessions spend tokens — attachment handling and long-history compaction.")}
              />
              <TokenSavingsCard />
              <CompactionCard />
            </section>
          ) : tab === "skills" ? (
            <SkillsTab onCreateSkill={onCreateSkill} />
          ) : tab === "voice" ? (
            <VoiceInputSection />
          ) : tab === "memory" ? (
            <MemorySection />
          ) : (
            <PersonasSection onOpenPersona={onOpenPersona} />
          )}
        </div>
      </div>
    </main>
  );
}

// -- Voice input: deliberate model provisioning + compatibility + microphone test (§37) --------
const voiceError = (error: unknown) =>
  error instanceof Error
    ? error.message
    : typeof error === "string"
      ? error
      : getI18n().getFixedT(null, "translation")("settings.voice_action_failed");

const formatBytes = (bytes: number) => {
  if (!bytes) return "0 MiB";
  return `${Math.round(bytes / 1024 / 1024)} MiB`;
};

/** `busyPack` sentinel for an action covering every pack — a pack id can never collide with it. */
const ALL_PACKS = "*";

function VoiceInputSection() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<DictationStatus | null>(null);
  // Progress arrives per pack, so "Download both" and a single card's bar read the same stream.
  const [progress, setProgress] = useState<Record<string, DictationDownloadProgress>>({});
  // Which pack an action is running against; ALL_PACKS while "Download both" is in flight.
  const [busyPack, setBusyPack] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "downloading" | "verifying" | "testing" | "transcribing">("idle");
  const [error, setError] = useState<string | null>(null);
  const [legacyCleaned, setLegacyCleaned] = useState(false);
  const [testTranscript, setTestTranscript] = useState("");
  const desktop = isTauri();

  const publish = (next: DictationStatus) => {
    setStatus(next);
    window.dispatchEvent(new CustomEvent("coworker:voice-input-changed", { detail: next }));
  };

  // The whisper-era model is dead weight once both packs verify, and `ocw-stt` refuses to remove
  // it before that — so this is safe to call after anything that could have completed the set.
  const sweepLegacy = async (next: DictationStatus) => {
    if (!next.legacy_model_present || !next.model_verified) return next;
    const removed = await cleanupLegacyDictationModels().catch(() => [] as string[]);
    if (!removed.length) return next;
    setLegacyCleaned(true);
    return (await getDictationStatus()) ?? next;
  };

  useEffect(() => {
    if (!desktop) return;
    let active = true;
    let unlisten = () => {};
    void listenDictationDownloadProgress((next) => {
      if (active) setProgress((current) => ({ ...current, [next.pack]: next }));
    }).then((stop) => {
      unlisten = stop;
    });
    void getDictationStatus().then(async (initial) => {
      if (!active || !initial) return;
      publish(await sweepLegacy(initial));
      // Every file is on disk at the right length but the verification marker no longer matches
      // (an interrupted upgrade, a touched file). Re-hash once, unprompted, rather than leaving
      // the user staring at a full set of packs the microphone still refuses to use.
      if (initial.model_installed && !initial.model_verified) {
        setPhase("verifying");
        setBusyPack(ALL_PACKS);
        try {
          const verified = await verifyDictationModel();
          if (active) publish(await sweepLegacy(verified));
        } catch (verifyError) {
          if (active) setError(voiceError(verifyError));
        } finally {
          if (active) {
            setPhase("idle");
            setBusyPack(null);
          }
        }
      }
    });
    return () => {
      active = false;
      unlisten();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktop]);

  /** One download run. `pack` undefined means every pack, in order. */
  const download = async (pack?: string) => {
    setError(null);
    setBusyPack(pack ?? ALL_PACKS);
    setPhase("downloading");
    try {
      publish(await sweepLegacy(await downloadDictationModel(pack)));
    } catch (downloadError) {
      setError(voiceError(downloadError));
      const latest = await getDictationStatus();
      if (latest) publish(latest);
    } finally {
      setPhase("idle");
      setBusyPack(null);
      setProgress({});
    }
  };

  const cancelDownload = async () => {
    await cancelDictationModelDownload().catch(() => undefined);
  };

  const verify = async (pack?: string) => {
    setError(null);
    setBusyPack(pack ?? ALL_PACKS);
    setPhase("verifying");
    try {
      publish(await sweepLegacy(await verifyDictationModel(pack)));
    } catch (verifyError) {
      setError(voiceError(verifyError));
      const latest = await getDictationStatus();
      if (latest) publish(latest);
    } finally {
      setPhase("idle");
      setBusyPack(null);
    }
  };

  const remove = async (pack: string) => {
    if (!window.confirm(t("settings.voice_delete_confirm"))) return;
    setError(null);
    try {
      publish(await deleteDictationModel(pack));
      setTestTranscript("");
      setProgress((current) => {
        const next = { ...current };
        delete next[pack];
        return next;
      });
    } catch (deleteError) {
      setError(voiceError(deleteError));
    }
  };

  const toggleTest = async () => {
    if (!status?.supported || !status.model_verified) return;
    setError(null);
    try {
      if (status.recording) {
        setPhase("transcribing");
        const transcript = (await stopDictation()).trim();
        setTestTranscript(transcript);
        if (!transcript) throw new Error(t("settings.voice_no_speech"));
        publish(await markDictationTestPassed());
      } else {
        setTestTranscript("");
        setPhase("testing");
        publish(await startDictation());
      }
    } catch (testError) {
      setError(voiceError(testError));
      const latest = await getDictationStatus();
      if (latest) publish(latest);
    } finally {
      setPhase("idle");
    }
  };

  // Every branch below reads from `packs` — the Rust side is the only place that knows what the
  // packs are, how big they are, or whether they are whole.
  const packs = status?.packs ?? [];
  const downloading = phase === "downloading" || !!status?.download_in_progress;
  const totalBytes = packs.reduce((sum, pack) => sum + pack.total_bytes, 0);
  const onDisk = packs.reduce(
    (sum, pack) => sum + (progress[pack.id]?.downloaded_bytes ?? pack.downloaded_bytes),
    0,
  );
  const allVerified = packs.length > 0 && packs.every((pack) => pack.verified);
  const anyMissing = packs.some((pack) => !pack.verified);
  const ready = !!status?.supported && !!status?.model_verified && !!status?.test_passed;

  const packCard = (pack: DictationPack) => {
    const live = progress[pack.id];
    const packBusy = busyPack === pack.id || busyPack === ALL_PACKS;
    // During "Download both" the packs are fetched one after another, so only the one actually
    // receiving bytes shows a bar. A queued pack sitting at 0% "file 1 of 2" reads as stuck.
    const packDownloading =
      downloading && (busyPack === pack.id || (busyPack === ALL_PACKS && !!live));
    const done = live?.downloaded_bytes ?? pack.downloaded_bytes;
    const percent = Math.min(100, Math.round((done / Math.max(pack.total_bytes, 1)) * 100));
    // Partly on disk but not whole: the button should say "resume", not "download", or a user who
    // stopped a 226 MiB download at 60% will assume they are starting over.
    const partial = !pack.installed && done > 0;
    return (
      <div className={CARD} key={pack.id} data-testid={`voice-pack-${pack.id}`}>
        <div className="p-4 flex items-center gap-3">
          <Icon name="mic" size={18} className={pack.verified ? "text-green-600 mt-0.5" : "text-muted mt-0.5"} />
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium">{t(pack.label_key)}</div>
            <div className="text-[12px] text-muted mt-0.5">
              {pack.verified
                ? t("settings.voice_installed", { size: formatBytes(pack.total_bytes) })
                : t("settings.voice_not_installed", { size: formatBytes(pack.total_bytes) })}
            </div>
            <div className="text-[12px] text-faint mt-0.5">
              {t(`settings.voice_pack_${pack.id}_detail`)}
            </div>
            {!pack.verified && pack.missing_files.length > 0 && (
              <div className="text-[12px] text-warnInk mt-0.5">
                {t("settings.voice_pack_files_missing", {
                  missing: pack.missing_files.length,
                  total: pack.file_count,
                })}
              </div>
            )}
          </div>
          {pack.verified ? (
            <>
              <span className="text-[12px] px-2 py-1 rounded-full bg-green-50 text-green-700">
                {t("settings.voice_verified")}
              </span>
              {/* No "Repair" here on purpose. Repair means "fetch the files that are missing or
                  wrong", and a verified pack has none — the engine skips a verified pack outright,
                  so the button would spin up nothing: no download, no progress bar, no error. If
                  the files go bad later, "Verify" is what notices, and the card flips to the
                  un-verified branch below, which offers Repair for real. */}
              <button className={BTN_BORDERED} disabled={!!busyPack} onClick={() => void verify(pack.id)}>
                {t("settings.voice_pack_verify")}
              </button>
              <button className="text-[12px] text-red-600 px-2 py-2" disabled={!!busyPack} onClick={() => void remove(pack.id)}>
                {t("settings.voice_delete")}
              </button>
            </>
          ) : packDownloading ? (
            <button className={BTN_BORDERED} onClick={() => void cancelDownload()}>{t("common.stop")}</button>
          ) : phase === "verifying" && packBusy ? (
            <span className="text-[12px] text-muted">{t("settings.voice_verifying")}</span>
          ) : (
            <>
              {pack.installed && (
                <button className={BTN_BORDERED} disabled={!!busyPack} onClick={() => void verify(pack.id)}>
                  {t("settings.voice_pack_verify")}
                </button>
              )}
              {/* Same call for all three labels: repair re-fetches only what is missing or the
                  wrong length — the pack directory is kept, so a single damaged file costs one
                  file, not the whole pack. */}
              <button className={BTN_ACCENT} disabled={!status?.supported || !!busyPack} onClick={() => void download(pack.id)}>
                {partial ? t("settings.voice_pack_resume") : pack.installed ? t("settings.voice_repair") : t("settings.voice_download")}
              </button>
            </>
          )}
        </div>
        {packDownloading && (
          <div className="border-t border-line px-4 py-3">
            <div className="h-1.5 rounded-full bg-line overflow-hidden">
              <div className="h-full bg-accent transition-all" style={{ width: `${percent}%` }} />
            </div>
            <div className="mt-1.5 text-[12px] text-muted flex">
              <span>
                {t("settings.voice_pack_progress", {
                  done: formatBytes(done),
                  total: formatBytes(pack.total_bytes),
                  index: live?.file_index ?? 1,
                  count: live?.file_count ?? pack.file_count,
                })}
              </span>
              <span className="ml-auto">{percent}%</span>
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <section>
      <PanelHead
        title={t("settings.tab.voice")}
        sub={t("settings.voice_intro")}
      />

      {!desktop ? (
        <div className={CARD + " p-4 text-[13px] text-muted"}>{t("settings.voice_desktop_only")}</div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl border border-green-200 bg-green-50/70 px-4 py-3 text-[13px] text-green-800">
            <span className="font-medium">{t("settings.voice_private_title")}</span>{" "}
            {t("settings.voice_private_body")}
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-start gap-3">
              <Icon name="code" size={18} className="text-accent mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium">{t("settings.voice_device_title")}</div>
                <div className="text-[12px] text-muted mt-1">{status?.device_summary || t("settings.voice_checking")}</div>
                {status?.compatibility_reason && <div className="text-[12px] text-red-600 mt-1.5">{t(status.compatibility_reason)}</div>}
              </div>
              {status && (
                <span className={"text-[12px] px-2 py-1 rounded-full " + (status.supported ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600")}>
                  {status.supported ? `● ${t("settings.voice_compatible")}` : t("settings.voice_unsupported")}
                </span>
              )}
            </div>
            <div className="border-t border-line bg-paper/50 px-4 py-3 grid grid-cols-2 gap-3 text-[12px] text-muted">
              <div><span className="block text-ink font-medium">{t("settings.voice_mac")}</span>{t("settings.voice_mac_detail")}</div>
              <div><span className="block text-ink font-medium">{t("settings.voice_windows")}</span>{t("settings.voice_windows_detail")}</div>
              <div><span className="block text-ink font-medium">{t("settings.voice_memory")}</span>{t("settings.voice_memory_detail")}</div>
              <div><span className="block text-ink font-medium">{t("settings.voice_processor")}</span>{t("settings.voice_processor_detail")}</div>
            </div>
          </div>

          {/* Two engines, two downloads: live text while you speak, and the pass that replaces it.
              Saying so here is what stops the streaming model's rough output reading as a bug. */}
          <div className={CARD + " p-4"}>
            <div className="text-[13px] font-medium">{t("settings.voice_engine_title")}</div>
            <div className="text-[12px] text-muted mt-1">
              {t("settings.voice_engine_detail", { engine: status?.engine || "" })}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="text-[13px] font-medium flex-1">{t("settings.voice_whisper_title")}</div>
            {anyMissing && (
              <button
                className={BTN_ACCENT}
                disabled={!status?.supported || !!busyPack || !packs.length}
                onClick={() => void download()}
              >
                {t("settings.voice_pack_download_all", { size: formatBytes(totalBytes) })}
              </button>
            )}
          </div>

          {busyPack === ALL_PACKS && downloading && (
            <div className={CARD + " px-4 py-3"} data-testid="voice-total-progress">
              <div className="h-1.5 rounded-full bg-line overflow-hidden">
                <div
                  className="h-full bg-accent transition-all"
                  style={{ width: `${Math.min(100, Math.round((onDisk / Math.max(totalBytes, 1)) * 100))}%` }}
                />
              </div>
              <div className="mt-1.5 text-[12px] text-muted">
                {t("settings.voice_pack_total_progress", {
                  done: formatBytes(onDisk),
                  total: formatBytes(totalBytes),
                })}
              </div>
            </div>
          )}

          {packs.map(packCard)}

          {legacyCleaned ? (
            <div className="rounded-lg border border-line bg-paper/50 px-3 py-2.5 text-[12px] text-muted" role="status">
              {t("settings.voice_legacy_cleaned")}
            </div>
          ) : status?.legacy_model_present ? (
            <div className="rounded-lg border border-line bg-paper/50 px-3 py-2.5 text-[12px] text-muted">
              {t("settings.voice_legacy_present")}
            </div>
          ) : null}

          <div className={CARD}>
            <div className="p-4 flex items-center gap-3">
              <Icon name="mic" size={18} className={ready ? "text-green-600" : "text-muted"} />
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium">{t("settings.voice_mic_test_title")}</div>
                <div className="text-[12px] text-muted mt-0.5">
                  {ready ? t("settings.voice_mic_test_ready") : t("settings.voice_mic_test_pending")}
                </div>
              </div>
              {ready && <span className="text-[12px] px-2 py-1 rounded-full bg-green-50 text-green-700">● {t("settings.voice_ready_badge")}</span>}
              <button className={BTN_BORDERED} disabled={!status?.supported || !allVerified || phase === "transcribing"} onClick={() => void toggleTest()}>
                {status?.recording
                  ? t("settings.voice_stop_check")
                  : phase === "transcribing"
                    ? t("settings.voice_transcribing")
                    : ready
                      ? t("settings.voice_test_again")
                      : t("settings.voice_test_mic")}
              </button>
            </div>
            {status?.recording && <div className="border-t border-line px-4 py-3 text-[12px] text-accent" role="status">{t("settings.voice_listening")}</div>}
            {testTranscript && <div className="border-t border-line bg-paper/50 px-4 py-3 text-[13px]">“{testTranscript}”</div>}
          </div>

          {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-[12px] text-red-700">{error}</div>}
        </div>
      )}
    </section>
  );
}

// -- Personas: installed/enabled/delete management, the dir/Git importer, and the
// entry point to the Persona Gallery (a screen-sized modal — installs finish back
// here, disabled pending consent; a gallery install re-mounts the list in place).
// The Gallery entry point is GONE (owner 2026-08-21) — coworkers install from
// GitHub / folder / zip only. GalleryModal stays in the tree for the gallery's
// possible return as a first-class distribution surface, but nothing mounts it.
function PersonasSection({ onOpenPersona }: { onOpenPersona?: (id: string) => void }) {
  const { t } = useTranslation();
  return (
    <section>
      <PanelHead title={t("settings.tab.personas")} sub={t("settings.personas_intro")} />
      <p className="text-[13px] text-muted leading-relaxed max-w-[560px] mt-5 mb-1">
        {t("settings.personas_desc")}
      </p>
      <PersonasTab onOpenPersona={onOpenPersona} />
    </section>
  );
}

// -- Appearance + app behaviour ------------------------------------------------
function AppearanceSection() {
  const { t } = useTranslation();
  const [theme, setTheme] = useThemePref();
  const [autostart, setAuto] = useState(false);
  const [keepAwake, setKeep] = useState(false);
  const desktop = isTauri();
  // "system" = no explicit choice persisted; the app follows the OS locale.
  const [currentLang, setCurrentLang] = useState<Lang | "system">(() => getStoredLanguage() ?? "system");

  useEffect(() => {
    if (isTauri()) {
      getAutostart().then((v) => setAuto(!!v));
      getKeepAwake().then((v) => setKeep(!!v));
    }
  }, []);

  const toggleAuto = async (v: boolean) => setAuto(!!(await setAutostart(v)));
  const toggleKeep = async (v: boolean) => setKeep(!!(await setKeepAwake(v)));
  const runSetupAgain = async () => {
    await setOnboarded(false);
    window.dispatchEvent(new CustomEvent("coworker:open-onboarding"));
  };
  const changeLang = (lang: Lang | "system") => {
    setCurrentLang(lang);
    void setI18nLanguage(lang === "system" ? null : lang);
  };

  return (
    <section>
      <PanelHead title={t("settings.general_title")} sub={t("settings.general_sub")} />

      <div className={CARD + " p-4 mb-4"}>
        <div className={FIELD_LABEL}>{t("settings.theme")}</div>
        <div className="seg mt-2.5" role="radiogroup" aria-label={t("settings.appearance_aria")}>
          {(["light", "dark", "auto"] as const).map((p) => (
            <button key={p} className={p === theme ? "active" : ""} onClick={() => setTheme(p)}>
              {p === "light" ? t("settings.theme_light") : p === "dark" ? t("settings.theme_dark") : t("settings.theme_auto")}
            </button>
          ))}
        </div>
        <div className={FIELD_HELP}>{t("settings.theme_auto_help")}</div>
      </div>

      <div className={CARD + " p-4 mb-4"}>
        <div className={FIELD_LABEL}>{t("settings.language")}</div>
        <div className="seg mt-2.5" role="radiogroup" aria-label={t("settings.language_aria")}>
          {(["system", "en", "zh"] as const).map((lng) => (
            <button
              key={lng}
              className={lng === currentLang ? "active" : ""}
              onClick={() => changeLang(lng)}
            >
              {lng === "zh" ? t("settings.language_zh") : lng === "en" ? t("settings.language_en") : t("settings.language_system")}
            </button>
          ))}
        </div>
        <div className={FIELD_HELP}>{t("settings.language_help")}</div>
      </div>

      <SidebarCard />

      <ContextBarCard />

      <AutoApproveCard />

      <FilesCard />

      <TrustedWorkspacesCard />

      {desktop && (
        <div className={CARD + " p-4"}>
          <div className={FIELD_LABEL + " mb-2.5"}>{t("settings.always_on")}</div>
          <label className="flex items-start gap-3 py-2">
            <input type="checkbox" className="mt-0.5" checked={autostart} onChange={(e) => toggleAuto(e.target.checked)} />
            <span>
              <span className="block text-[13px] text-ink">{t("settings.open_at_login")}</span>
              <span className="block text-[12px] text-muted">{t("settings.open_at_login_help")}</span>
            </span>
          </label>
          <label className="flex items-start gap-3 py-2">
            <input type="checkbox" className="mt-0.5" checked={keepAwake} onChange={(e) => toggleKeep(e.target.checked)} />
            <span>
              <span className="block text-[13px] text-ink">{t("settings.keep_awake")}</span>
              <span className="block text-[12px] text-muted">{t("settings.keep_awake_help")}</span>
            </span>
          </label>
        </div>
      )}

      {/* One card for the app-lifecycle actions (UX-021): the onboarding replay (§24 —
          every build, the browser dev shell runs the same first-run flow) and, on
          desktop, the manual update check (launch also checks automatically). */}
      <div className={CARD + " p-4 mt-4"}>
        <div className={FIELD_LABEL + " mb-2"}>{t("settings.setup_updates")}</div>
        <div className="flex items-center gap-2">
          <button className={BTN_BORDERED} onClick={runSetupAgain}>
            {t("settings.run_setup_again")}
          </button>
          {desktop && <UpdateInline />}
        </div>
        <div className={FIELD_HELP}>{t("settings.run_setup_help")}</div>
      </div>
    </section>
  );
}

function TrustedWorkspacesCard() {
  const { t } = useTranslation();
  const [workspaces, setWorkspaces] = useState<WorkspaceCommandTrust[] | null>(null);
  // A fetch failure has security semantics here (unlike a plain loading state) — it must
  // never collapse into the same rendering as "no workspaces are trusted", so it gets its
  // own flag rather than being coerced into an empty list.
  const [loadFailed, setLoadFailed] = useState(false);

  const refresh = () => {
    setLoadFailed(false);
    getTrustedWorkspaces()
      .then(setWorkspaces)
      // Keep the last good list on a failed refresh (e.g. after a revoke); a never-loaded
      // card shows the retry copy instead.
      .catch(() => setLoadFailed(true));
  };

  useEffect(() => {
    refresh();
  }, []);

  const revoke = async (path: string) => {
    if (!window.confirm(t("settings.trust_revoke_confirm", { path }))) return;
    await setWorkspaceTrusted(path, false);
    refresh();
  };

  return (
    <div className={CARD + " p-4 mb-4"} data-testid="trusted-workspaces-card">
      <div className={FIELD_LABEL}>{t("settings.trusted_workspaces")}</div>
      <div className={FIELD_HELP}>
        {t("settings.trusted_workspaces_help")}
      </div>
      {loadFailed && workspaces === null ? (
        <div className="text-[12px] text-muted mt-3">
          <div>{t("settings.trust_load_failed")}</div>
          <button
            className={BTN_BORDERED + " mt-2"}
            onClick={refresh}
            data-testid="trusted-workspaces-retry"
          >
            {t("common.retry")}
          </button>
        </div>
      ) : workspaces === null ? (
        <div className="text-[12px] text-muted mt-3">{t("settings.trust_loading")}</div>
      ) : workspaces.length === 0 ? (
        <div className="text-[12px] text-muted mt-3">{t("settings.trust_empty")}</div>
      ) : (
        <div className="mt-3 divide-y divide-line">
          {workspaces.map((workspace) => (
            <div key={workspace.workspace} className="py-2.5 flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-[13px] text-ink break-all">{workspace.workspace}</div>
                <div className="text-[12px] text-muted mt-0.5">
                  {workspace.requested_commands.length
                    ? t("settings.trust_allowances", { count: workspace.requested_commands.length })
                    : t("settings.trust_no_allowances")}
                  {!workspace.exists ? t("settings.trust_folder_unavailable") : ""}
                </div>
              </div>
              <button
                className="text-[12px] text-red-600 px-2 py-1"
                onClick={() => void revoke(workspace.workspace)}
              >
                {t("settings.trust_revoke")}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function UpdateInline() {
  const { t } = useTranslation();
  const [state, setState] = useState<"idle" | "checking" | "none" | "found" | "installing" | "error">("idle");
  const [version, setVersion] = useState("");

  const check = async () => {
    setState("checking");
    try {
      const u = await checkForUpdate();
      if (u) {
        setVersion(u.version);
        setState("found");
      } else {
        setState("none");
      }
    } catch {
      setState("error");
    }
  };

  const install = async () => {
    setState("installing");
    try {
      await installUpdate(); // success restarts the app
    } catch {
      setState("error");
    }
  };

  return (
    <span className="inline-flex items-center gap-2.5">
      {state === "found" ? (
        <button className={BTN_BORDERED} onClick={install} data-testid="settings-update-install">
          {t("settings.update_install", { version })}
        </button>
      ) : (
        <button
          className={BTN_BORDERED}
          onClick={check}
          disabled={state === "checking" || state === "installing"}
          data-testid="settings-update-check"
        >
          {state === "checking" ? t("settings.checking") : t("settings.check_for_updates")}
        </button>
      )}
      {(state === "none" || state === "error" || state === "installing") && (
        <span className="text-[12px] text-muted">
          {state === "none"
            ? t("settings.update_latest")
            : state === "error"
              ? t("settings.update_error")
              : t("settings.update_downloading")}
        </span>
      )}
    </span>
  );
}

// Telemetry/Privacy card removed for this release (owner ask 2026-07-22); the
// setCloudTelemetry API stays for a future opt-out surface.

// -- Sidebar density -------------------------------------------------------------
// -- Token savings (PDF attachments; owner ask, 2026-07-17) ---------------------
// Attachments replay with EVERY turn, so a big PDF quietly multiplies token spend.
// This card is the attachment dial: attach thresholds + the fallback for models
// without native PDF support. (Long-history spend is handled by auto-compaction —
// the CompactionCard below, OPE-27.)
function TokenSavingsCard() {
  const { t } = useTranslation();
  const [pdf, setPdf] = useState<PdfSettings | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) =>
        setPdf({
          pdf_fallback: s.pdf_fallback || "text",
          pdf_max_pages: s.pdf_max_pages || 20,
          pdf_max_mb: s.pdf_max_mb || 10,
        }),
      )
      .catch(() => setPdf({ pdf_fallback: "text", pdf_max_pages: 20, pdf_max_mb: 10 }));
  }, []);

  const save = async (patch: Partial<PdfSettings>) => {
    setPdf((p) => (p ? { ...p, ...patch } : p));
    await setPdfSettings(patch);
  };

  if (!pdf) return null;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="token-savings-card">
      <div className={FIELD_LABEL}>{t("settings.token_savings")}</div>
      <div className={FIELD_HELP}>
        {t("settings.token_savings_help")}
      </div>

      <div className="mt-3 text-[13px] text-ink">{t("settings.pdf_fallback_label")}</div>
      <div className="seg mt-2" role="radiogroup" aria-label={t("settings.pdf_fallback_aria")} data-testid="pdf-fallback">
        <button
          className={pdf.pdf_fallback === "text" ? "active" : ""}
          onClick={() => save({ pdf_fallback: "text" })}
        >
          {t("settings.pdf_extract_text")}
        </button>
        <button
          className={pdf.pdf_fallback === "images" ? "active" : ""}
          onClick={() => save({ pdf_fallback: "images" })}
        >
          {t("settings.pdf_send_images")}
        </button>
      </div>
      <div className={FIELD_HELP}>
        {t("settings.pdf_fallback_help")}
      </div>

      <div className="mt-3 flex items-center gap-5">
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">{t("settings.pdf_max_pages")}</span>
          <input
            type="number"
            min={1}
            max={100}
            value={pdf.pdf_max_pages}
            data-testid="pdf-max-pages"
            className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) => save({ pdf_max_pages: Math.max(1, Math.min(Number(e.target.value) || 20, 100)) })}
          />
        </label>
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">{t("settings.pdf_max_size")}</span>
          <input
            type="number"
            min={1}
            max={10}
            value={pdf.pdf_max_mb}
            data-testid="pdf-max-mb"
            className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) => save({ pdf_max_mb: Math.max(1, Math.min(Number(e.target.value) || 10, 10)) })}
          />
          <span className="text-[13px] text-muted">MB</span>
        </label>
      </div>
      <div className={FIELD_HELP}>
        {t("settings.pdf_limits_help")}
      </div>
    </div>
  );
}

// -- Context compaction (OPE-27) ------------------------------------------------
// Long sessions are summarized automatically when they approach the model's context
// limit, so work continues instead of hitting a raw provider error. Two spec'd
// overrides (trigger % + token cap) and the summarizer-model pin — nothing more.
function CompactionCard() {
  const { t } = useTranslation();
  const [cfg, setCfg] = useState<CompactionSettings | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [labels, setLabels] = useState<Record<string, string>>({});

  useEffect(() => {
    getSettings()
      .then((s) => {
        setCfg({
          compaction_threshold_pct: s.compaction_threshold_pct ?? 0.8,
          compaction_cap_tokens: s.compaction_cap_tokens ?? 250_000,
          compaction_model: s.compaction_model ?? "",
        });
        setModels(s.models || []);
        setLabels(s.model_labels || {});
      })
      .catch(() =>
        setCfg({
          compaction_threshold_pct: 0.8,
          compaction_cap_tokens: 250_000,
          compaction_model: "",
        }),
      );
  }, []);

  const save = async (patch: Partial<CompactionSettings>) => {
    setCfg((p) => (p ? { ...p, ...patch } : p));
    await setCompactionSettings(patch);
  };

  if (!cfg) return null;
  const modelLabel = (id: string) => labels[id]?.split(" · ")[0] || id;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="compaction-card">
      <div className={FIELD_LABEL}>{t("Context compaction")}</div>
      <div className={FIELD_HELP}>
        {t("Long sessions are compacted automatically: older turns are summarized so the coworker keeps working instead of running out of context. Your visible transcript is never changed — a small marker shows where compaction happened.")}
      </div>

      <div className="mt-3 flex items-center gap-5 flex-wrap">
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">{t("Compact at")}</span>
          <input
            type="number"
            min={10}
            max={95}
            value={Math.round(cfg.compaction_threshold_pct * 100)}
            data-testid="compaction-threshold"
            className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) =>
              save({
                compaction_threshold_pct:
                  Math.max(10, Math.min(Number(e.target.value) || 80, 95)) / 100,
              })
            }
          />
          <span className="text-[13px] text-muted">% of the context window</span>
        </label>
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">{t("or at")}</span>
          <input
            type="number"
            min={10_000}
            max={2_000_000}
            step={10_000}
            value={cfg.compaction_cap_tokens}
            data-testid="compaction-cap"
            className="w-28 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) =>
              save({
                compaction_cap_tokens: Math.max(
                  10_000,
                  Math.min(Number(e.target.value) || 250_000, 2_000_000),
                ),
              })
            }
          />
          <span className="text-[13px] text-muted">tokens, whichever is smaller</span>
        </label>
      </div>
      <div className={FIELD_HELP}>
        {t("The cap makes very-large-context models compact early — quality and speed degrade well before their nominal limit.")}
      </div>

      <div className="mt-3 flex items-center gap-2.5">
        <span className="text-[13px] text-ink">{t("Summarizer model")}</span>
        <select
          value={cfg.compaction_model}
          data-testid="compaction-model"
          className="px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
          onChange={(e) => save({ compaction_model: e.target.value })}
        >
          <option value="">{t("Session’s own model (default)")}</option>
          {sortModelIds(models).map((m) => (
            <option key={m} value={m}>
              {modelLabel(m)}
            </option>
          ))}
        </select>
      </div>
      <div className={FIELD_HELP}>
        {t("The summary is written by this model. The default follows whatever model the session is using.")}
      </div>
    </div>
  );
}

// -- Composer: context-window bar (owner ask 2026-07-30) ------------------------
// The chip's bar is context-window occupancy; the session total (unbounded) lives in
// the popover. Some people would rather not watch a meter at all, hence the toggle.
function ContextBarCard() {
  const { t } = useTranslation();
  const [shown, setShown] = useState<boolean | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setShown(s.context_bar === true))
      .catch(() => setShown(false));
  }, []);

  const save = async (next: boolean) => {
    setShown(next);
    await setContextBar(next);
  };

  if (shown === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="context-bar-card">
      <div className={FIELD_LABEL}>{t("settings.composer_section")}</div>
      <label className="flex items-start gap-3 py-2">
        <input
          type="checkbox"
          className="mt-0.5"
          data-testid="context-bar-toggle"
          checked={shown}
          onChange={(e) => save(e.target.checked)}
        />
        <span>
          <span className="block text-[13px] text-ink">{t("settings.context_bar_title")}</span>
          <span className="block text-[12px] text-muted">{t("settings.context_bar_desc")}</span>
        </span>
      </label>
    </div>
  );
}

// Auto-Approve (spec §1.5): the experimental feature flag that adds the "Auto-Approve" mode
// to the composer's mode picker, plus its shadow-evaluation sibling. Both default off and are
// user-global (a cloned repo can't turn either on). Shadow is nested under the main flag — it
// only makes sense to measure the reviewer once you know what it is.
function AutoApproveCard() {
  const { t } = useTranslation();
  const [on, setOn] = useState<boolean | null>(null);
  const [shadow, setShadow] = useState(false);

  useEffect(() => {
    getSettings()
      .then((s) => {
        setOn(s.auto_approve === true);
        setShadow(s.auto_approve_shadow === true);
      })
      .catch(() => setOn(false));
  }, []);

  const saveOn = async (next: boolean) => {
    setOn(next);
    await setAutoApprove(next);
  };
  const saveShadow = async (next: boolean) => {
    setShadow(next);
    await setAutoApproveShadow(next);
  };

  if (on === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="auto-approve-card">
      {/* Upstream shipped this whole card with no i18n at all — not even one of their own
          dotted keys — so it arrived in the 2026-08-31 merge as bare English sitting in an
          otherwise Chinese Settings page. Keyed here on the English source (the fork's legacy
          scheme), which lives only in zh-CN.json and therefore can never conflict upstream. */}
      <div className={FIELD_LABEL}>{t("Auto-approve (experimental)")}</div>
      <label className="flex items-start gap-3 py-2">
        <input
          type="checkbox"
          className="mt-0.5"
          data-testid="auto-approve-toggle"
          checked={on}
          onChange={(e) => saveOn(e.target.checked)}
        />
        <span>
          <span className="block text-[13px] text-ink">{t("Enable Auto-approve mode")}</span>
          <span className="block text-[12px] text-muted">
            <Trans
              i18nKey="Adds an <em>Auto-approve</em> option to the mode picker. In that mode, your session model reviews each action that would normally need approval and clears the routine ones; anything doubtful still asks you. It can never allow something the rules block. One extra model call per check, billed to your usage."
              components={{ em: <em /> }}
            />
          </span>
        </span>
      </label>
      <label className="flex items-start gap-3 py-2 pl-7">
        <input
          type="checkbox"
          className="mt-0.5"
          data-testid="auto-approve-shadow-toggle"
          checked={shadow}
          onChange={(e) => saveShadow(e.target.checked)}
        />
        <span>
          <span className="block text-[13px] text-ink">
            {t("Shadow evaluation")} <span className="text-faint">{t("(for measuring)")}</span>
          </span>
          <span className="block text-[12px] text-muted">
            <Trans
              i18nKey="On any mode, the reviewer records what it <em>would</em> have decided next to your own choice — without changing anything. Lets you see how it would behave before trusting it. Also costs one model call per approval."
              components={{ em: <em /> }}
            />
          </span>
        </span>
      </label>
    </div>
  );
}

function SidebarCard() {
  const { t } = useTranslation();
  const [peek, setPeek] = useState<number | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setPeek(s.sessions_peek || 5))
      .catch(() => setPeek(5));
  }, []);

  const save = async (n: number) => {
    const clamped = Math.max(1, Math.min(n || 5, 50));
    setPeek(clamped);
    await setSessionsPeek(clamped);
  };

  if (peek === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"}>
      <div className={FIELD_LABEL}>{t("settings.sidebar_card_title")}</div>
      <label className="flex items-center gap-3 mt-2.5">
        <span className="text-[13px] text-ink">{t("settings.sidebar_per_coworker")}</span>
        <input
          type="number"
          min={1}
          max={50}
          value={peek}
          className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
          onChange={(e) => save(Number(e.target.value))}
        />
      </label>
      <div className={FIELD_HELP}>
        {t("settings.sidebar_card_help")}
      </div>
    </div>
  );
}

// -- Files (scratch location) — one card inside General (UX-021: a single option
// doesn't earn its own tab) -----------------------------------------------------
// Item 6: unset is a first-class, always-working state — not just a placeholder string
// until the first session provisions it. The server creates + grants it eagerly at
// startup (SessionManager.ensure_scratch_base) and degrades to this same default when a
// configured location turns out to be unwritable, so the UI mirrors that: the input stays
// blank (an actual value, not a display trick) while unset, its placeholder shows exactly
// where files land (`scratch_base_effective`), and submitting blank is a valid "reset to
// default" action rather than a disabled/rejected one.
const DEFAULT_SCRATCH_BASE = "~/OpenWorker";

function FilesCard() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [scratchDraft, setScratchDraft] = useState("");
  const [scratchMsg, setScratchMsg] = useState<string | null>(null);
  const [scratchMsgError, setScratchMsgError] = useState(false);
  const desktop = isTauri();

  const refresh = () =>
    getSettings()
      .then((s) => {
        setSettings(s);
        setScratchDraft((d) =>
          d || (s.scratch_base && s.scratch_base !== DEFAULT_SCRATCH_BASE ? s.scratch_base : ""),
        );
      })
      .catch(() => setSettings(null));
  useEffect(() => {
    refresh();
  }, []);

  const saveScratch = async () => {
    setScratchMsg(null);
    setScratchMsgError(false);
    const path = scratchDraft.trim();
    const res = await setScratchBase(path);
    if (res.ok) {
      setScratchMsg(path ? t("settings.files_saved") : t("settings.files_reset_done"));
      refresh();
    } else {
      setScratchMsg(res.error || t("settings.files_save_error"));
      setScratchMsgError(true);
    }
  };
  const browseScratch = async () => {
    const picked = await pickFolder();
    if (picked) setScratchDraft(picked);
  };

  if (!settings) return null;

  // Older backends don't send `scratch_base_effective` yet — fall back to the raw field
  // (which was always a real, if unresolved, path) so the placeholder never renders blank.
  const effectivePath = settings.scratch_base_effective || settings.scratch_base || DEFAULT_SCRATCH_BASE;
  const isUnset = !settings.scratch_base || settings.scratch_base === DEFAULT_SCRATCH_BASE;

  return (
    <div className={CARD + " p-4 mb-4"}>
      <div className={FIELD_LABEL}>{t("settings.files_title")}</div>
        <div className="flex items-center gap-2 mt-2.5">
          <input
            className={INPUT}
            type="text"
            placeholder={effectivePath}
            value={scratchDraft}
            spellCheck={false}
            autoComplete="off"
            onChange={(e) => setScratchDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !isComposing(e) && saveScratch()}
          />
          {desktop && (
            <button className={BTN_BORDERED} onClick={browseScratch} title={t("settings.files_pick_folder")}>
              {t("settings.files_browse")}
            </button>
          )}
          <button className={BTN_ACCENT} onClick={saveScratch}>
            {t("settings.files_save")}
          </button>
        </div>
      <div className={FIELD_HELP}>
        {t("settings.files_help")}{" "}
        {t("settings.files_default_hint", { path: effectivePath })}
        {isUnset && ` ${t("settings.files_unset_hint")}`}
      </div>
      {settings.scratch_base_error && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-[12px] text-red-700 mt-2.5">
          {t("settings.files_unwritable", { error: settings.scratch_base_error })}
        </div>
      )}
      {scratchMsg &&
        (scratchMsgError ? (
          <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-[12px] text-red-700 mt-2.5">
            {scratchMsg}
          </div>
        ) : (
          <div className="text-[13px] text-muted mt-2.5">{scratchMsg}</div>
        ))}
    </div>
  );
}
