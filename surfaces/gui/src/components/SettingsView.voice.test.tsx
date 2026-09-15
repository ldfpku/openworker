// Voice Input now provisions TWO model packs — live text while you speak, and the pass that
// re-transcribes the recording when you stop. VoiceInputSection isn't exported on its own, so
// this renders SettingsView on its "voice" tab with ../api and ../tauri mocked, the way
// SettingsView.trust.test.tsx does for the General tab.
//
// The point of every case below is the same: the SPA holds no opinion about what the packs are.
// Names, sizes, file counts and readiness all come from the Rust side's `packs` array, and the
// UI is a pure function of it.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SettingsView } from "./SettingsView";

vi.mock("../api", () => ({
  getSettings: vi.fn(async () => ({ scratch_base: "~/OpenWorker", sessions_peek: 5, context_bar: false })),
  getTrustedWorkspaces: vi.fn(async () => [] as unknown[]),
  setAutoApprove: vi.fn(async () => ({ ok: true })),
  setAutoApproveShadow: vi.fn(async () => ({ ok: true })),
  setCompactionSettings: vi.fn(async () => ({ ok: true })),
  setContextBar: vi.fn(async () => ({ ok: true })),
  setOnboarded: vi.fn(async () => ({ ok: true, onboarded: false })),
  setPdfSettings: vi.fn(async () => ({ ok: true })),
  setScratchBase: vi.fn(async () => ({ ok: true })),
  setSessionsPeek: vi.fn(async () => ({ ok: true })),
  setWorkspaceTrusted: vi.fn(async () => ({ ok: true })),
}));

const STREAMING_BYTES = 237_202_501; // 226 MiB
const FINAL_BYTES = 239_549_735; // 228 MiB

type Pack = {
  id: string;
  label_key: string;
  repo: string;
  revision: string;
  installed: boolean;
  verified: boolean;
  total_bytes: number;
  downloaded_bytes: number;
  file_count: number;
  missing_files: string[];
};

const pack = (id: string, bytes: number, files: number, extra: Partial<Pack> = {}): Pack => ({
  id,
  label_key: `settings.voice_pack_${id}`,
  repo: `csukuangfj/sherpa-onnx-${id}`,
  revision: "0".repeat(40),
  installed: true,
  verified: true,
  total_bytes: bytes,
  downloaded_bytes: bytes,
  file_count: files,
  missing_files: [],
  ...extra,
});

const status = (packs: Pack[], extra: Record<string, unknown> = {}) => ({
  recording: false,
  model_installed: packs.every((entry) => entry.installed),
  model_verified: packs.every((entry) => entry.verified),
  test_passed: false,
  download_in_progress: false,
  model_name: "Paraformer + SenseVoice (local)",
  model_bytes: packs.reduce((sum, entry) => sum + entry.total_bytes, 0),
  engine: "sherpa-onnx 1.13.7",
  packs,
  legacy_model_present: false,
  supported: true,
  device_summary: "Windows 10.0.26200 · x64",
  compatibility_reason: null,
  ...extra,
});

const READY = status([pack("streaming", STREAMING_BYTES, 3), pack("final", FINAL_BYTES, 2)]);
const NOTHING_INSTALLED = status([
  pack("streaming", STREAMING_BYTES, 3, { installed: false, verified: false, downloaded_bytes: 0, missing_files: ["encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt"] }),
  pack("final", FINAL_BYTES, 2, { installed: false, verified: false, downloaded_bytes: 0, missing_files: ["model.int8.onnx", "tokens.txt"] }),
]);

const mocks = vi.hoisted(() => ({
  getDictationStatus: vi.fn(),
  downloadDictationModel: vi.fn(),
  verifyDictationModel: vi.fn(),
  deleteDictationModel: vi.fn(),
  cleanupLegacyDictationModels: vi.fn(),
  progressHandler: { current: null as null | ((p: unknown) => void) },
}));

vi.mock("../tauri", () => ({
  isTauri: () => true,
  getDictationStatus: mocks.getDictationStatus,
  downloadDictationModel: mocks.downloadDictationModel,
  verifyDictationModel: mocks.verifyDictationModel,
  deleteDictationModel: mocks.deleteDictationModel,
  cleanupLegacyDictationModels: mocks.cleanupLegacyDictationModels,
  cancelDictationModelDownload: vi.fn(async () => undefined),
  markDictationTestPassed: vi.fn(async () => READY),
  startDictation: vi.fn(async () => READY),
  stopDictation: vi.fn(async () => "hello"),
  listenDictationDownloadProgress: vi.fn(async (handler: (p: unknown) => void) => {
    mocks.progressHandler.current = handler;
    return () => {
      mocks.progressHandler.current = null;
    };
  }),
  getAutostart: vi.fn(async () => false),
  setAutostart: vi.fn(async () => false),
  getKeepAwake: vi.fn(async () => false),
  setKeepAwake: vi.fn(async () => false),
  checkForUpdate: vi.fn(async () => null),
  installUpdate: vi.fn(async () => undefined),
  pickFolder: vi.fn(async () => null),
}));

/** Push one download-progress event, exactly as the shell emits it. */
const fireProgress = async (payload: Record<string, unknown>) => {
  await act(async () => {
    mocks.progressHandler.current?.(payload);
  });
};

const openVoice = async () => {
  render(<SettingsView initialTab="voice" />);
  await screen.findByTestId("voice-pack-streaming");
};

beforeEach(() => {
  mocks.getDictationStatus.mockResolvedValue(READY);
  mocks.downloadDictationModel.mockResolvedValue(READY);
  mocks.verifyDictationModel.mockResolvedValue(READY);
  mocks.deleteDictationModel.mockResolvedValue(NOTHING_INSTALLED);
  mocks.cleanupLegacyDictationModels.mockResolvedValue([]);
  mocks.progressHandler.current = null;
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SettingsView — Voice Input model packs", () => {
  it("renders one card per pack, with sizes derived from the pack manifest", async () => {
    await openVoice();

    expect(screen.getByText("Live text · streaming Paraformer")).toBeTruthy();
    expect(screen.getByText("Final transcript · SenseVoice")).toBeTruthy();
    // 237202501 B and 239549735 B, through formatBytes — never a hard-coded string.
    expect(screen.getByText("Installed and verified · 226 MiB")).toBeTruthy();
    expect(screen.getByText("Installed and verified · 228 MiB")).toBeTruthy();
    // The engine line names the stack the Rust side reported.
    expect(screen.getByText(/sherpa-onnx 1\.13\.7/)).toBeTruthy();
  });

  it("offers Download both at the sum of the packs, and nothing once they are ready", async () => {
    mocks.getDictationStatus.mockResolvedValue(NOTHING_INSTALLED);
    await openVoice();

    // 476752236 B -> 455 MiB. The button text is computed, not written down anywhere.
    const all = await screen.findByText("Download both (455 MiB)");
    fireEvent.click(all);
    await waitFor(() => expect(mocks.downloadDictationModel).toHaveBeenCalledWith(undefined));

    cleanup();
    mocks.getDictationStatus.mockResolvedValue(READY);
    await openVoice();
    expect(screen.queryByText(/^Download both/)).toBeNull();
  });

  it("routes verify and delete at the pack the user pressed", async () => {
    await openVoice();
    const card = screen.getByTestId("voice-pack-final");

    fireEvent.click(within(card, "Verify"));
    await waitFor(() => expect(mocks.verifyDictationModel).toHaveBeenCalledWith("final"));

    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(within(card, "Delete"));
    await waitFor(() => expect(mocks.deleteDictationModel).toHaveBeenCalledWith("final"));
  });

  it("offers no Repair on a verified pack — every button on a card has to do something", async () => {
    // The engine skips a pack that is already verified, so "Repair" here would start nothing:
    // no download, no progress bar, no error. A dead button is worse than a missing one, and
    // "Verify" is the control that actually re-reads the bytes.
    await openVoice();
    const card = screen.getByTestId("voice-pack-final");
    expect(card.textContent).toContain("Verified");
    expect(card.textContent).not.toContain("Repair");

    for (const label of ["Verify", "Delete"]) within(card, label);
  });

  it("offers Repair — and routes it at that pack — once a pack stops verifying", async () => {
    const damaged = status([
      pack("streaming", STREAMING_BYTES, 3),
      pack("final", FINAL_BYTES, 2, { verified: false, missing_files: ["tokens.txt"] }),
    ]);
    mocks.getDictationStatus.mockResolvedValue(damaged);
    // Opening the tab on an installed-but-unverified pack re-hashes it; the re-hash has to
    // agree, or the card flips back to verified before the assertions below run.
    mocks.verifyDictationModel.mockResolvedValue(damaged);
    await openVoice();

    const card = screen.getByTestId("voice-pack-final");
    expect(card.textContent).toContain("Repair");
    fireEvent.click(within(card, "Repair"));
    await waitFor(() => expect(mocks.downloadDictationModel).toHaveBeenCalledWith("final"));
    // The healthy pack next to it is untouched, and still shows no Repair of its own.
    expect(screen.getByTestId("voice-pack-streaming").textContent).not.toContain("Repair");
  });

  it("says Resume, not Download, when a pack is part-way onto the disk", async () => {
    mocks.getDictationStatus.mockResolvedValue(
      status([
        pack("streaming", STREAMING_BYTES, 3, {
          installed: false,
          verified: false,
          downloaded_bytes: 120_000_000,
          missing_files: ["encoder.int8.onnx"],
        }),
        pack("final", FINAL_BYTES, 2),
      ]),
    );
    await openVoice();

    const card = screen.getByTestId("voice-pack-streaming");
    expect(card.textContent).toContain("Resume download");
    expect(card.textContent).toContain("1 of 3 files missing or damaged");
  });

  it("drives each card's progress bar from the pack its events name", async () => {
    mocks.getDictationStatus.mockResolvedValue(NOTHING_INSTALLED);
    // Hold the download open so the in-flight UI is observable.
    let finish: (value: unknown) => void = () => {};
    mocks.downloadDictationModel.mockImplementation(
      () => new Promise((resolve) => { finish = resolve; }),
    );
    await openVoice();

    fireEvent.click(await screen.findByText("Download both (455 MiB)"));
    await waitFor(() => expect(mocks.progressHandler.current).toBeTruthy());
    await fireProgress({
      pack: "streaming",
      downloaded_bytes: 104_857_600,
      total_bytes: STREAMING_BYTES,
      file_index: 2,
      file_count: 3,
    });

    expect(screen.getByTestId("voice-pack-streaming").textContent).toContain(
      "100 MiB of 226 MiB · file 2 of 3",
    );
    // The final pack has not been touched yet, so its card shows no progress of its own.
    expect(screen.getByTestId("voice-pack-final").textContent).not.toContain("file 1 of");
    // The aggregate bar counts both packs: 100 MiB done of 455 MiB.
    expect(screen.getByTestId("voice-total-progress").textContent).toContain("100 MiB of 455 MiB");

    await act(async () => {
      finish(READY);
    });
  });

  it("clears the whisper-era model once both packs verify, and says so", async () => {
    mocks.getDictationStatus
      .mockResolvedValueOnce(status(READY.packs as Pack[], { legacy_model_present: true }))
      .mockResolvedValue(READY);
    mocks.cleanupLegacyDictationModels.mockResolvedValue(["ggml-base.bin"]);

    await openVoice();

    await waitFor(() => expect(mocks.cleanupLegacyDictationModels).toHaveBeenCalled());
    expect(
      await screen.findByText(
        "The previous Whisper model has been removed. Please test the microphone once more.",
      ),
    ).toBeTruthy();
  });

  it("leaves the old model alone while a pack is still missing", async () => {
    mocks.getDictationStatus.mockResolvedValue(
      status(NOTHING_INSTALLED.packs as Pack[], { legacy_model_present: true }),
    );
    await openVoice();

    expect(
      screen.getByText(
        "The previous Whisper model is still on disk. It is removed automatically once both packs verify.",
      ),
    ).toBeTruthy();
    expect(mocks.cleanupLegacyDictationModels).not.toHaveBeenCalled();
  });

  it("re-hashes on open when the files are all there but the marker no longer matches", async () => {
    const stale = status([
      pack("streaming", STREAMING_BYTES, 3, { verified: false }),
      pack("final", FINAL_BYTES, 2, { verified: false }),
    ]);
    mocks.getDictationStatus.mockResolvedValue(stale);
    mocks.verifyDictationModel.mockResolvedValue(READY);

    await openVoice();

    // Everything is on disk at the right length; only the verification marker is stale, and the
    // microphone stays locked until it is refreshed. Doing it unprompted beats a dead mic button.
    // No pack argument at all: the sweep covers every pack.
    await waitFor(() => expect(mocks.verifyDictationModel).toHaveBeenCalledWith());
    expect(await screen.findByText("Installed and verified · 226 MiB")).toBeTruthy();
  });

  it("surfaces a download failure without losing the cards", async () => {
    mocks.getDictationStatus.mockResolvedValue(NOTHING_INSTALLED);
    mocks.downloadDictationModel.mockRejectedValue(new Error("hf-mirror.com is unreachable."));
    await openVoice();

    fireEvent.click(await screen.findByText("Download both (455 MiB)"));
    expect((await screen.findByRole("alert")).textContent).toContain("hf-mirror.com is unreachable.");
    expect(screen.getByTestId("voice-pack-streaming")).toBeTruthy();
  });
});

/** The one button with this label inside this card — the two cards carry the same labels. */
function within(card: HTMLElement, label: string): HTMLElement {
  const button = Array.from(card.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.trim() === label,
  );
  if (!button) throw new Error(`no "${label}" button in ${card.dataset.testid}`);
  return button as HTMLElement;
}
