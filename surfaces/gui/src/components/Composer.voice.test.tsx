// §37 voice input — the composer's side of the contract, driven through a mocked
// __TAURI__ global (the mic is native-only; the browser build renders no mic at all).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Composer } from "./Composer";
import { initIme, resetImeForTest } from "../ime";

// The composition guard reads document-level state, which only exists once main.tsx's
// initIme() has run. Mirror that here so the IME cases below are the real code path.
initIme();

const pack = (id: string, bytes: number) => ({
  id,
  label_key: `settings.voice_pack_${id}`,
  repo: `csukuangfj/${id}`,
  revision: "0".repeat(40),
  installed: true,
  verified: true,
  total_bytes: bytes,
  downloaded_bytes: bytes,
  file_count: id === "streaming" ? 3 : 2,
  missing_files: [] as string[],
});

const READY = {
  recording: false,
  model_installed: true,
  model_verified: true,
  test_passed: true,
  download_in_progress: false,
  model_name: "Paraformer + SenseVoice (local)",
  model_bytes: 476752236,
  engine: "sherpa-onnx 1.13.7",
  packs: [pack("streaming", 237202501), pack("final", 239549735)],
  legacy_model_present: false,
  supported: true,
  device_summary: "macOS 15 · Apple Silicon",
  compatibility_reason: null,
};
const NOT_READY = { ...READY, model_verified: false, test_passed: false };
const RECORDING = { ...READY, recording: true };

// Named LivePartial, not Partial: the props helper below uses TypeScript's built-in Partial<T>.
type LivePartial = { seq: number; text: string; committed_chars: number; degraded: boolean };

let invoke: ReturnType<typeof vi.fn>;
/** Handlers the component registered, by event name — how the live-transcript tests speak. */
let listeners: Record<string, ((event: { payload: unknown }) => void)[]>;

/** Deliver one `dictation-partial-transcript` exactly as the shell would. */
const firePartial = async (partial: LivePartial) => {
  await act(async () => {
    for (const handler of listeners["dictation-partial-transcript"] ?? []) {
      handler({ payload: partial });
    }
  });
};

/** Dispatch a composition event the way an input method does: on the document, bubbling. */
const composition = async (type: "compositionstart" | "compositionend") => {
  await act(async () => {
    document.dispatchEvent(new Event(type, { bubbles: true }));
  });
};

const composerBox = () => screen.getByPlaceholderText(/Ask the coworker/) as HTMLTextAreaElement;

/** Start a recording and wait until the partial listener is subscribed. */
const startRecording = async () => {
  fireEvent.click(await screen.findByLabelText("Start dictation"));
  const stop = await screen.findByLabelText("Stop dictation");
  await waitFor(() => expect(listeners["dictation-partial-transcript"]?.length).toBeGreaterThan(0));
  return stop;
};

const props = (extra: Partial<Parameters<typeof Composer>[0]> = {}) => ({
  mode: "interactive",
  model: "gpt-5.6-sol",
  running: false,
  connected: true,
  onSend: vi.fn(),
  onInterrupt: vi.fn(),
  onModeChange: vi.fn(),
  onModelChange: vi.fn(),
  ...extra,
});

beforeEach(() => {
  invoke = vi.fn(async (cmd: string) => {
    if (cmd === "get_dictation_status") return READY;
    if (cmd === "start_dictation") return RECORDING;
    if (cmd === "stop_dictation") return "hello from the mic";
    return null;
  });
  listeners = {};
  (globalThis as any).__TAURI__ = {
    core: { invoke },
    event: {
      listen: async (name: string, handler: (event: { payload: unknown }) => void) => {
        (listeners[name] ??= []).push(handler);
        return () => {
          listeners[name] = (listeners[name] ?? []).filter((entry) => entry !== handler);
        };
      },
    },
  };
});

afterEach(() => {
  cleanup();
  resetImeForTest();
  vi.unstubAllGlobals();
  delete (globalThis as any).__TAURI__;
});

describe("Composer voice input (§37)", () => {
  it("renders no mic at all outside the desktop app", () => {
    delete (globalThis as any).__TAURI__;
    render(<Composer {...props()} />);
    expect(screen.queryByLabelText(/dictation|Voice Input/)).toBeNull();
  });

  it("not ready → muted mic deep-links to Settings instead of recording", async () => {
    invoke.mockImplementation(async (cmd: string) =>
      cmd === "get_dictation_status" ? NOT_READY : null,
    );
    const onConfigureVoiceInput = vi.fn();
    render(<Composer {...props({ onConfigureVoiceInput })} />);

    const mic = await screen.findByLabelText("Configure Voice Input in Settings");
    expect(mic.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(mic);
    await waitFor(() => expect(onConfigureVoiceInput).toHaveBeenCalled());
    expect(invoke).not.toHaveBeenCalledWith("start_dictation", undefined);
  });

  it("ready → record shows the waveform and protects Send; stop inserts an editable draft", async () => {
    render(<Composer {...props()} />);

    fireEvent.click(await screen.findByLabelText("Start dictation"));
    const stop = await screen.findByLabelText("Stop dictation");
    expect(document.querySelector(".voice-wave-bars")).toBeTruthy();
    expect(screen.getByLabelText("Send").hasAttribute("disabled")).toBe(true);

    invoke.mockImplementation(async (cmd: string) => {
      if (cmd === "stop_dictation") return "hello from the mic";
      if (cmd === "get_dictation_status") return READY;
      return null;
    });
    fireEvent.click(stop);
    await screen.findByLabelText("Start dictation"); // recording UI wound down
    const box = screen.getByPlaceholderText(/Ask the coworker/) as HTMLTextAreaElement;
    expect(box.value).toBe("hello from the mic"); // a DRAFT — nothing auto-sent
    expect(document.querySelector(".voice-wave-bars")).toBeNull();
  });

  it("live updates land in the composer as they arrive", async () => {
    render(<Composer {...props()} />);
    await startRecording();

    await firePartial({ seq: 1, text: "你好", committed_chars: 0, degraded: false });
    expect(composerBox().value).toBe("你好");
    // Each update is the WHOLE transcript so far: the span is replaced, not appended to.
    await firePartial({ seq: 2, text: "你好世界", committed_chars: 2, degraded: false });
    expect(composerBox().value).toBe("你好世界");
  });

  it("an out-of-order update is dropped instead of rewinding the text", async () => {
    render(<Composer {...props()} />);
    await startRecording();

    await firePartial({ seq: 1, text: "你好", committed_chars: 0, degraded: false });
    await firePartial({ seq: 2, text: "你好世界", committed_chars: 2, degraded: false });
    // seq 1 arriving late would otherwise delete two characters the user has already seen.
    await firePartial({ seq: 1, text: "你好", committed_chars: 0, degraded: false });
    expect(composerBox().value).toBe("你好世界");
  });

  it("stopping replaces the live text with the final transcript rather than appending it", async () => {
    render(<Composer {...props()} />);
    const stop = await startRecording();

    await firePartial({ seq: 1, text: "你好", committed_chars: 0, degraded: false });
    await firePartial({ seq: 2, text: "你好世界", committed_chars: 0, degraded: false });

    invoke.mockImplementation(async (cmd: string) => {
      if (cmd === "stop_dictation") return "你好，世界。";
      if (cmd === "get_dictation_status") return READY;
      return null;
    });
    fireEvent.click(stop);
    await screen.findByLabelText("Start dictation");
    // Exactly the final transcript — not the live text with the final one glued on the end.
    expect(composerBox().value).toBe("你好，世界。");
  });

  // The engine cannot show the closing word while the user is still saying it: this model gives
  // up its last characters only once silence has followed them, so at the instant Stop is pressed
  // the live text is a word or so behind (measured: three characters on an eight-second
  // sentence). Stopping is what recovers them — the engine drains the recognizer and sends ONE
  // more update, which lands while `stop_dictation` is still off transcribing. If the composer
  // stopped listening the moment the button was pressed, the user would watch their last words
  // never arrive and the recording would look truncated until the final transcript replaced it a
  // second or more later. So that update has to land, and the final still replaces it.
  it("the tail the stop recovers lands in the box before the final transcript does", async () => {
    render(<Composer {...props()} />);
    const stop = await startRecording();
    await firePartial({ seq: 1, text: "明天下午三", committed_chars: 0, degraded: false });

    let finish = (_transcript: string) => {};
    invoke.mockImplementation(async (cmd: string) => {
      if (cmd === "stop_dictation") return new Promise<string>((resolve) => (finish = resolve));
      if (cmd === "get_dictation_status") return READY;
      return null;
    });
    fireEvent.click(stop);

    // The recording is still open as far as the shell is concerned; the drained tail arrives here.
    await firePartial({ seq: 2, text: "明天下午三点开会", committed_chars: 0, degraded: false });
    expect(composerBox().value).toBe("明天下午三点开会");

    await act(async () => {
      finish("明天下午3点开会。");
    });
    await screen.findByLabelText("Start dictation");
    expect(composerBox().value).toBe("明天下午3点开会。");
  });

  it("dictating mid-draft replaces only the span the caret opened", async () => {
    render(<Composer {...props()} />);
    const box = composerBox();
    fireEvent.change(box, { target: { value: "会议纪要 以上" } });
    // Caret between the two words: dictation belongs there, not at the end of the draft.
    box.setSelectionRange(5, 5);
    const stop = await startRecording();

    await firePartial({ seq: 1, text: "今天的会议", committed_chars: 0, degraded: false });
    expect(composerBox().value).toBe("会议纪要 今天的会议以上");

    invoke.mockImplementation(async (cmd: string) => {
      if (cmd === "stop_dictation") return "今天的会议。";
      if (cmd === "get_dictation_status") return READY;
      return null;
    });
    fireEvent.click(stop);
    await screen.findByLabelText("Start dictation");
    expect(composerBox().value).toBe("会议纪要 今天的会议。以上");
  });

  it("an update arriving mid-composition waits for the input method to finish", async () => {
    // Writing into the textarea while a candidate list is open rewrites the text under it and
    // cancels the word being typed. The update is parked and written on compositionend instead.
    render(<Composer {...props()} />);
    await startRecording();

    await composition("compositionstart");
    await firePartial({ seq: 1, text: "你好", committed_chars: 0, degraded: false });
    expect(composerBox().value).toBe("");

    await composition("compositionend");
    expect(composerBox().value).toBe("你好");
  });

  it("a newer update supersedes a parked one instead of rewinding to it later", async () => {
    // isComposing() also guards the 50 ms after compositionend, so an update can be parked with
    // no compositionend left to flush it. Left on the shelf, the NEXT composition would flush it
    // and rewind the live text two updates.
    render(<Composer {...props()} />);
    await startRecording();

    await composition("compositionstart");
    await firePartial({ seq: 1, text: "你好", committed_chars: 0, degraded: false });
    await composition("compositionend");
    expect(composerBox().value).toBe("你好");

    // Past the tail: this one is written straight through and clears the shelf.
    await new Promise((r) => setTimeout(r, 80));
    await firePartial({ seq: 2, text: "你好世界", committed_chars: 2, degraded: false });
    expect(composerBox().value).toBe("你好世界");

    await composition("compositionstart");
    await composition("compositionend");
    expect(composerBox().value).toBe("你好世界");
  });

  it("Escape while composing cancels the candidate, not the recording", async () => {
    // The window-level Escape is what throws a recording away. Without the composition guard,
    // backing out of a half-typed Chinese word took the whole recording with it.
    render(<Composer {...props()} />);
    await startRecording();
    await firePartial({ seq: 1, text: "你好", committed_chars: 0, degraded: false });

    await composition("compositionstart");
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(invoke).not.toHaveBeenCalledWith("cancel_dictation", undefined);
    expect(screen.getByLabelText("Stop dictation")).toBeTruthy();
    expect(composerBox().value).toBe("你好");

    // Composition over (and past the tail): Escape is the user's again.
    await composition("compositionend");
    await new Promise((r) => setTimeout(r, 80));
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("cancel_dictation", undefined));
    await screen.findByLabelText("Start dictation");
    expect(composerBox().value).toBe("");
  });

  it("the degraded notice goes away with the recording it describes", async () => {
    render(<Composer {...props()} />);
    const stop = await startRecording();

    await firePartial({ seq: 1, text: "你好", committed_chars: 0, degraded: true });
    // By text, not by role: the recording timer is a role="status" live region too.
    await screen.findByText(/Live text is unavailable/);

    fireEvent.click(stop);
    await screen.findByLabelText("Start dictation");
    // The recording is over and its final transcript is already in the box: "live text gave up"
    // has nothing left to describe.
    expect(screen.queryByText(/Live text is unavailable/)).toBeNull();
  });

  it("starting to dictate drops the enhanced-prompt state it would otherwise fight", async () => {
    // Both features own the same textarea. A "restore" landing after the mic has rewritten the
    // draft would put back a version of it that no longer exists.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ ok: true, text: "a clearer prompt" }) }) as Response),
    );
    render(<Composer {...props()} />);
    fireEvent.change(composerBox(), { target: { value: "help me" } });
    fireEvent.click(screen.getByRole("button", { name: "Enhance prompt" }));
    await waitFor(() => expect(composerBox().value).toBe("a clearer prompt"));
    expect(screen.getByRole("button", { name: "Restore original prompt" })).toBeTruthy();

    // The enhance button is hidden for the duration of a recording, so the state it would have
    // been left in only becomes visible again after Stop — which is exactly when a stray
    // "Restore" would be one click away from undoing what was just dictated.
    const stop = await startRecording();
    fireEvent.click(stop);
    await screen.findByLabelText("Start dictation");
    // The draft the enhance pass produced is still there — dictation added to it, it did not
    // replace it. That is precisely why the "Restore" backup pointing at the pre-enhance text
    // must be gone: restoring it now would delete what was just dictated.
    expect(composerBox().value).toBe("a clearer prompt hello from the mic");
    expect(screen.queryByRole("button", { name: "Restore original prompt" })).toBeNull();
    expect(screen.getByRole("button", { name: "Enhance prompt" })).toBeTruthy();
  });

  it("a start failure surfaces the error and never wedges the mic", async () => {
    invoke.mockImplementation(async (cmd: string) => {
      if (cmd === "get_dictation_status") return READY;
      if (cmd === "start_dictation") throw new Error("No microphone is available.");
      return null;
    });
    render(<Composer {...props()} />);

    fireEvent.click(await screen.findByLabelText("Start dictation"));
    expect((await screen.findByRole("alert")).textContent).toContain("No microphone is available.");
    expect(screen.getByLabelText("Start dictation").hasAttribute("disabled")).toBe(false);
  });
});
