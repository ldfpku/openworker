// Thin bridge to the Tauri desktop shell. In the browser these are inert (isTauri() === false),
// so the SPA stays a single codebase. We use the injected `window.__TAURI__` global (the shell
// sets `withGlobalTauri`) instead of the @tauri-apps npm packages, so the browser build needs
// no Tauri dependencies.

import i18n from "./i18n";

export const isTauri = (): boolean =>
  typeof (globalThis as any).__TAURI__ !== "undefined";

// "macos" | "windows" | "linux" — injected by the shell (std::env::consts::OS) before the
// SPA loads; userAgent fallback covers browser dev. The macOS overlay-titlebar layout (and
// its traffic-light compensations) must NEVER apply on Windows, which keeps its native
// title bar (alignment bug, caught on Windows 2026-07-21).
export const platformOS = (): string => {
  const injected = (globalThis as any).__OCW_PLATFORM__;
  if (typeof injected === "string" && injected) return injected;
  return /mac/i.test(navigator.userAgent) ? "macos" : /win/i.test(navigator.userAgent) ? "windows" : "linux";
};

/** One downloadable model pack. `label_key` is an i18n key owned by the Rust side, so the two
 * cards in Settings are whatever `ocw-stt` says the packs are — the SPA never hard-codes the
 * list, the sizes, or the names. */
export type DictationPack = {
  id: string;
  label_key: string;
  repo: string;
  revision: string;
  installed: boolean;
  verified: boolean;
  total_bytes: number;
  /** Bytes already on disk, complete files and resumable parts alike — drives "resume". */
  downloaded_bytes: number;
  file_count: number;
  /** Files absent or the wrong length: exactly what "Repair" would re-fetch. */
  missing_files: string[];
};

export type DictationStatus = {
  recording: boolean;
  /** Derived: true only when EVERY pack is installed / verified. */
  model_installed: boolean;
  model_verified: boolean;
  test_passed: boolean;
  download_in_progress: boolean;
  model_name: string;
  model_bytes: number;
  /** Recognition stack, for display ("sherpa-onnx 1.13.7"). */
  engine: string;
  packs: DictationPack[];
  /** A whisper-era ggml-base.bin is still on disk; removed once both packs verify. */
  legacy_model_present: boolean;
  supported: boolean;
  device_summary: string;
  compatibility_reason: string | null;
};

/** Per-pack progress. Aggregate across packs in the UI when the user asked for everything. */
export type DictationDownloadProgress = {
  pack: string;
  downloaded_bytes: number;
  total_bytes: number;
  /** 1-based index of the file being fetched, for "2 / 3" style detail. */
  file_index: number;
  file_count: number;
};

/** A live transcript update while recording. `text` is the WHOLE live transcript so far, never a
 * delta: the composer replaces its dictation span with it. `seq` is monotonic per recording —
 * drop anything not greater than the last one seen. `committed_chars` is the prefix the engine
 * will no longer revise. `degraded` means live text has been given up on for this recording
 * (the machine cannot keep up, or the streaming model failed to load); the recording and the
 * final transcript are unaffected. */
export type DictationPartial = {
  seq: number;
  text: string;
  committed_chars: number;
  degraded: boolean;
};

const invoke = async <T>(cmd: string, args?: Record<string, unknown>): Promise<T | null> => {
  const tauri = (globalThis as any).__TAURI__;
  if (!tauri?.core?.invoke) return null;
  try {
    return (await tauri.core.invoke(cmd, args)) as T;
  } catch {
    return null;
  }
};

const invokeStrict = async <T>(cmd: string, args?: Record<string, unknown>): Promise<T> => {
  const tauri = (globalThis as any).__TAURI__;
  if (!tauri?.core?.invoke) throw new Error(i18n.t("This feature is available in the desktop app."));
  return (await tauri.core.invoke(cmd, args)) as T;
};

/** Open the native macOS folder picker (Tauri only). Returns the chosen path, or null. */
export async function pickFolder(): Promise<string | null> {
  const path = await invoke<string>("pick_folder");
  return typeof path === "string" && path ? path : null;
}

/** The folder picker that works EVERYWHERE: Tauri's native dialog in the desktop shell, else the
 * sidecar-opened OS dialog (the sidecar is local, so the browser GUI still gets a real picker —
 * owner report 2026-07-04: "Browse" was desktop-only and the browser had paste-a-path only). */
export async function chooseFolder(): Promise<string | null> {
  if (isTauri()) return pickFolder();
  const { pickFolderViaServer } = await import("./api");
  return pickFolderViaServer();
}

/** Open-at-login (macOS LaunchAgent). */
export const getAutostart = () => invoke<boolean>("get_autostart");
export const setAutostart = (enabled: boolean) => invoke<boolean>("set_autostart", { enabled });

/** Keep this system awake so scheduled tasks fire while idle (caffeinate on macOS,
 * SetThreadExecutionState on Windows). Persists across restarts. */
export const getKeepAwake = () => invoke<boolean>("get_keep_awake");
export const setKeepAwake = (enabled: boolean) => invoke<boolean>("set_keep_awake", { enabled });

/** Begin native window dragging from a custom title/header region. */
export const startWindowDrag = () => invoke<boolean>("start_window_drag");

// Local dictation is native-only. The browser build deliberately keeps this unavailable rather
// than silently sending microphone audio to a server.
export const getDictationStatus = () => invoke<DictationStatus>("get_dictation_status");
/** Instantaneous mic loudness 0..1 while recording (0 otherwise) — drives the composer's
 * live waveform. Cheap; poll at ~10Hz. */
export const getDictationLevel = () => invoke<number>("dictation_level");
/** The interface language rides along unused: SenseVoice transcribes in `auto`, and a future
 * "always transcribe as <lang>" override should not need a protocol change to turn on. */
export const startDictation = () =>
  invokeStrict<DictationStatus>("start_dictation", { language: i18n.language });
/** Stops recording and returns the final transcript: the whole recording re-transcribed with
 * punctuation. It REPLACES the live text the composer has been showing rather than extending
 * it, so callers must overwrite, not append. */
export const stopDictation = () => invokeStrict<string>("stop_dictation");
export const cancelDictation = () => invokeStrict<void>("cancel_dictation");
/** `pack` names one model pack; omit it to bring every pack up to date in order. */
export const downloadDictationModel = (pack?: string) =>
  invokeStrict<DictationStatus>("download_dictation_model", { pack: pack ?? null });
export const cancelDictationModelDownload = () => invokeStrict<void>("cancel_dictation_model_download");
export const verifyDictationModel = (pack?: string) =>
  invokeStrict<DictationStatus>("verify_dictation_model", { pack: pack ?? null });
export const markDictationTestPassed = () => invokeStrict<DictationStatus>("mark_dictation_test_passed");
export const deleteDictationModel = (pack?: string) =>
  invokeStrict<DictationStatus>("delete_dictation_model", { pack: pack ?? null });
/** Removes the whisper-era model once both new packs verify; returns what was removed (empty
 * when there was nothing to remove, or the packs are not both ready yet). */
export const cleanupLegacyDictationModels = () =>
  invokeStrict<string[]>("cleanup_legacy_dictation_models");

export async function listenDictationDownloadProgress(
  handler: (progress: DictationDownloadProgress) => void,
): Promise<() => void> {
  const listen = (globalThis as any).__TAURI__?.event?.listen;
  if (!listen) return () => {};
  return (await listen("dictation-download-progress", (event: { payload: DictationDownloadProgress }) => {
    handler(event.payload);
  })) as () => void;
}

/** Live transcript updates while recording. Unsubscribe when the recording ends. */
export async function listenDictationPartialTranscript(
  handler: (partial: DictationPartial) => void,
): Promise<() => void> {
  const listen = (globalThis as any).__TAURI__?.event?.listen;
  if (!listen) return () => {};
  return (await listen("dictation-partial-transcript", (event: { payload: DictationPartial }) => {
    handler(event.payload);
  })) as () => void;
}

// --- Auto-update (desktop only; browser builds see null / throw) -----------------

export type UpdateInfo = { version: string; notes: string };

/** Ask the shell whether a newer release exists (verified manifest; see lib.rs).
 * null = up to date, unreachable endpoint, or not the desktop app. */
export const checkForUpdate = () => invoke<UpdateInfo | null>("check_for_update");

/** Pre-fetch + verify the update bytes in the background so the install is instant.
 * The shell caches them keyed by version; calling again for the same version is a no-op.
 * Rejects when there is no update or the download fails — callers fall back to the
 * download-on-install path. */
export const downloadUpdate = () => invokeStrict<void>("download_update");

/** Drop the pre-fetched update bundle (freed on "Later" so a dismissed release
 * doesn't pin tens of MB for a weeks-long app run). */
export const clearPendingUpdate = () => invokeStrict<void>("clear_pending_update");

/** Install the update (pre-fetched bytes when available, else download + verify now),
 * then relaunch. Resolves only on failure paths (success restarts the process on macOS;
 * Windows hands off to the installer). */
export const installUpdate = () => invokeStrict<void>("install_update");

/** Best-effort open a URL in the user's browser. Uses the Tauri opener plugin if present, else
 * `window.open`. The caller should also render the raw URL so it stays copyable if both no-op
 * (the desktop webview has no opener plugin wired yet). */
export function openExternal(url: string): void {
  const opener = (globalThis as any).__TAURI__?.opener;
  if (opener?.openUrl) {
    opener.openUrl(url).catch(() => window.open(url, "_blank", "noopener,noreferrer"));
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}
