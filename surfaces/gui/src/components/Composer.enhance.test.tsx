// Composer "Enhance prompt" button (item 1): idle (sparkle, "Enhance prompt") → busy (stop,
// "Enhancing… click to cancel" — a click aborts) → enhanced (refresh, "Restore original
// prompt"). POST /v1/prompt/enhance is session-agnostic — no sessionId is needed here. The
// button has no test id (IconButton's `label` is its accessible name), so tests find it by
// that name, the same way a sighted user finds it by its tooltip.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Composer } from "./Composer";

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

const box = () => screen.getByPlaceholderText(/Ask the coworker/) as HTMLTextAreaElement;
const enhanceBtn = () => screen.getByRole("button", { name: "Enhance prompt" });
const restoreBtn = () => screen.getByRole("button", { name: "Restore original prompt" });
const busyBtn = () => screen.getByRole("button", { name: "Enhancing… click to cancel" });

function okJson(body: unknown) {
  return vi.fn(async (_url: string, _init?: RequestInit) => ({ ok: true, json: async () => body }) as Response);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Composer — enhance prompt", () => {
  it("is disabled while the draft is empty", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<Composer {...props()} />);
    expect((enhanceBtn() as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(box(), { target: { value: "help me plan a trip" } });
    expect((enhanceBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("replaces the draft on success, sends {text, model}, and flips to the restore state", async () => {
    const fetchMock = okJson({ ok: true, text: "a much clearer prompt" });
    vi.stubGlobal("fetch", fetchMock);
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(box().value).toBe("a much clearer prompt"));
    expect(restoreBtn()).toBeTruthy();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain("/v1/prompt/enhance");
    expect(JSON.parse(init.body as string)).toEqual({ text: "help me", model: "gpt-5.6-sol" });
  });

  it("restores the pre-enhance text on a second click and returns to idle", async () => {
    vi.stubGlobal("fetch", okJson({ ok: true, text: "enhanced version" }));
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(box().value).toBe("enhanced version"));

    fireEvent.click(restoreBtn());
    expect(box().value).toBe("help me");
    expect(enhanceBtn()).toBeTruthy();
  });

  it("editing the enhanced text still restores the original (edits don't clear the backup)", async () => {
    vi.stubGlobal("fetch", okJson({ ok: true, text: "enhanced version" }));
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(box().value).toBe("enhanced version"));

    fireEvent.change(box(), { target: { value: "enhanced version, with a tweak" } });
    expect(restoreBtn()).toBeTruthy(); // still enhanced — an edit alone doesn't reset
    fireEvent.click(restoreBtn());
    expect(box().value).toBe("help me");
  });

  it("clicking while busy cancels: the request's signal aborts and the text is unchanged", async () => {
    let capturedInit: RequestInit | undefined;
    const fetchMock = vi.fn((_url: unknown, init?: RequestInit) => {
      capturedInit = init;
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(busyBtn()).toBeTruthy());

    fireEvent.click(busyBtn());
    await waitFor(() => expect(capturedInit?.signal?.aborted).toBe(true));
    expect(box().value).toBe("help me");
    await waitFor(() => expect(enhanceBtn()).toBeTruthy());
    expect(screen.queryByRole("alert")).toBeNull(); // a cancel is not a failure
  });

  it("ok:false from the backend (still HTTP 200) shows the failure copy and never writes undefined", async () => {
    vi.stubGlobal("fetch", okJson({ ok: false, error: "provider down" }));
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe("Couldn't enhance the prompt. Please try again."),
    );
    expect(box().value).toBe("help me");
    expect(enhanceBtn()).toBeTruthy(); // back to idle, not stuck busy
  });

  it("a network/JSON error also shows the failure copy without overwriting the draft", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(box().value).toBe("help me");
  });

  it("submit() clears the enhance cache — the next draft starts idle, not enhanced", async () => {
    const onSend = vi.fn();
    vi.stubGlobal("fetch", okJson({ ok: true, text: "enhanced version" }));
    render(<Composer {...props({ onSend })} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(box().value).toBe("enhanced version"));

    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("enhanced version", [], undefined);
    await waitFor(() => expect(box().value).toBe(""));

    fireEvent.change(box(), { target: { value: "a fresh message" } });
    expect(enhanceBtn()).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Restore original prompt" })).toBeNull();
  });

  it("clearing the draft to empty after enhancing drops back to idle", async () => {
    vi.stubGlobal("fetch", okJson({ ok: true, text: "enhanced version" }));
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(box().value).toBe("enhanced version"));

    fireEvent.change(box(), { target: { value: "" } });
    await waitFor(() => expect((enhanceBtn() as HTMLButtonElement).disabled).toBe(true));
    expect(screen.queryByRole("button", { name: "Restore original prompt" })).toBeNull();
  });
});
