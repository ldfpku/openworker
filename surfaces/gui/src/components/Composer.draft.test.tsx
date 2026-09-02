// The unsent draft survives a surface switch (owner ask 2026-09-02): Settings/Inbox/Library
// unmount the composer, so the draft is lifted to the owner and handed back on the next mount.
// A mount never clears — a restored draft belongs to THIS conversation; only a later
// resetKey change (a different conversation) wipes it.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Composer, type ComposerDraft } from "./Composer";
import type { Attachment } from "../types";

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response),
  );
}

const props = (extra: Partial<Parameters<typeof Composer>[0]> = {}) => ({
  mode: "interactive",
  model: "gpt-5.6-sol",
  running: false,
  connected: true,
  sessionId: "s1",
  onSend: vi.fn(),
  onInterrupt: vi.fn(),
  onModeChange: vi.fn(),
  onModelChange: vi.fn(),
  ...extra,
});

const box = () => screen.getByPlaceholderText(/Ask the coworker/) as HTMLTextAreaElement;

const NOTES: Attachment = { kind: "text", name: "notes.txt", text: "remember this" };

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Composer — the draft survives a surface switch", () => {
  it("mounts with the handed-back draft: text and attachment chip are both there", () => {
    stubFetch();
    const draft: ComposerDraft = { text: "precious draft", attachments: [NOTES], skill: null };
    render(<Composer {...props({ draft, resetKey: "s1" })} />);
    expect(box().value).toBe("precious draft");
    expect(screen.getByText("notes.txt")).toBeTruthy();
  });

  it("unmount + remount with the reported draft restores it; the mount never clears", async () => {
    stubFetch();
    const onDraftChange = vi.fn();
    render(<Composer {...props({ resetKey: "s1", onDraftChange })} />);
    fireEvent.change(box(), { target: { value: "half a thought" } });
    await waitFor(() =>
      expect(onDraftChange).toHaveBeenLastCalledWith({
        text: "half a thought",
        attachments: [],
        skill: null,
      }),
    );
    const reported: ComposerDraft = onDraftChange.mock.lastCall![0];

    cleanup(); // Settings takes over the surface — the composer is gone
    stubFetch();
    render(<Composer {...props({ resetKey: "s1", draft: reported })} />);
    expect(box().value).toBe("half a thought");
    // …and it stays: the mount-time clear must not fire a tick later either.
    await waitFor(() => expect(box().value).toBe("half a thought"));
  });

  it("a remount does NOT re-apply the prefill the previous instance already consumed", async () => {
    // Escape out of the send-folder dialog prefills the composer; the user then edits the
    // text and takes a Settings round-trip. `composerPrefill` is state the owner never
    // clears, so the remount still carries it — re-applying it would overwrite the very
    // draft this mount just restored.
    stubFetch();
    const prefill = { text: "fix the tests", nonce: 1 };
    const draft: ComposerDraft = {
      text: "fix the flaky auth test instead",
      attachments: [],
      skill: null,
    };
    render(<Composer {...props({ resetKey: "s1", prefill, draft })} />);
    expect(box().value).toBe("fix the flaky auth test instead");
    await waitFor(() => expect(box().value).toBe("fix the flaky auth test instead"));
  });

  it("a mount with a prefill and NO draft still applies it (the Skills/Library doorway)", async () => {
    stubFetch();
    render(<Composer {...props({ resetKey: "s9", prefill: { text: "Build me a skill that…", nonce: 4 } })} />);
    await waitFor(() => expect(box().value).toBe("Build me a skill that…"));
  });

  it("a genuinely new prefill still lands on a mount that restored a draft", async () => {
    stubFetch();
    const draft: ComposerDraft = { text: "half a thought", attachments: [], skill: null };
    const { rerender } = render(
      <Composer {...props({ resetKey: "s1", prefill: { text: "old", nonce: 1 }, draft })} />,
    );
    expect(box().value).toBe("half a thought");
    rerender(
      <Composer {...props({ resetKey: "s1", prefill: { text: "brand new", nonce: 2 }, draft })} />,
    );
    await waitFor(() => expect(box().value).toBe("brand new"));
  });

  it("a resetKey change still clears, and the empty draft is reported", async () => {
    stubFetch();
    const onDraftChange = vi.fn();
    const draft: ComposerDraft = { text: "old session text", attachments: [NOTES], skill: null };
    const { rerender } = render(
      <Composer {...props({ resetKey: "s1", draft, onDraftChange })} />,
    );
    expect(box().value).toBe("old session text");

    rerender(<Composer {...props({ resetKey: "s2", onDraftChange })} />);
    await waitFor(() => expect(box().value).toBe(""));
    expect(screen.queryByText("notes.txt")).toBeNull();
    expect(onDraftChange).toHaveBeenLastCalledWith({ text: "", attachments: [], skill: null });
  });
});
