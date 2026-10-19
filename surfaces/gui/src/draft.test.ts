// A draft stays a draft while the transcript holds only mode bookkeeping (owner ask
// 2026-09-02): the setup row stays, the model stays choosable, the header states no facts.
import { afterEach, describe, expect, it, vi } from "vitest";
import { draftStorageKey, hasConversation, readStoredDraft, writeStoredDraft } from "./draft";
import { itemsFromMessages } from "./itemsFromMessages";
import type { Item } from "./types";

describe("hasConversation (draft vs started)", () => {
  it("an empty transcript is a draft", () => {
    expect(hasConversation([])).toBe(false);
  });

  it("mode bookkeeping alone is a draft — banner and one-line markers both", () => {
    const items: Item[] = [
      {
        kind: "notice",
        tone: "info",
        title: "Auto-approve is on.",
        text: "Auto-approve uses a model to let routine actions through without asking.",
        bookkeeping: true,
      },
      { kind: "notice", tone: "info", text: "Ask for approval is on.", bookkeeping: true },
    ];
    expect(hasConversation(items)).toBe(false);
  });

  it("a real notice (connect error) ends the draft", () => {
    const items: Item[] = [{ kind: "notice", tone: "warn", text: "Connection lost.", retriable: true }];
    expect(hasConversation(items)).toBe(true);
  });

  it("a user turn ends the draft, bookkeeping around it notwithstanding", () => {
    const items: Item[] = [
      { kind: "notice", tone: "info", text: "Discuss is on.", bookkeeping: true },
      { kind: "user", text: "hello" },
    ];
    expect(hasConversation(items)).toBe(true);
  });

  // The live WS handler and the history replay must agree, or a draft that is REPLAYED —
  // resumed at boot, or reopened after a surface switch — loses its draft phase on reload
  // while the server still treats it as a draft.
  it("a REPLAYED transcript of pure bookkeeping is still a draft", () => {
    const items = itemsFromMessages([
      {
        role: "notice",
        kind: "mode_notice",
        title: "Auto-approve is on.",
        text: "Auto-approve uses a model to let routine actions through without asking.",
      },
      { role: "notice", kind: "mode_switch", text: "Discuss is on." },
      { role: "notice", kind: "model_switch", text: "Model switched to Kimi K2.6 · Moonshot" },
    ] as any);
    expect(items).toHaveLength(3);
    expect(hasConversation(items)).toBe(false);
  });

  it("a replayed transcript with a real turn is started", () => {
    const items = itemsFromMessages([
      { role: "notice", kind: "mode_switch", text: "Discuss is on." },
      { role: "user", content: "hello" },
    ] as any);
    expect(hasConversation(items)).toBe(true);
  });
});

// The unsent text survives a page reload (upstream f24b3fd4 / b90c02d5): per session in
// localStorage, text only, removed the moment the box is empty, never an error.
describe("composer draft storage (reload)", () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("keys per session under coworker:composer-draft:v1:<id>", () => {
    expect(draftStorageKey("abc")).toBe("coworker:composer-draft:v1:abc");
  });

  it("round-trips text, per session; nothing stored reads as undefined (not an empty draft)", () => {
    expect(readStoredDraft("s1")).toBeUndefined();
    writeStoredDraft("s1", "half a thought");
    expect(readStoredDraft("s1")).toBe("half a thought");
    expect(readStoredDraft("s2")).toBeUndefined();
    expect(localStorage.getItem("coworker:composer-draft:v1:s1")).toBe("half a thought");
  });

  it("empty text removes the entry (sent / cleared) and an empty session id is ignored", () => {
    writeStoredDraft("s1", "half a thought");
    writeStoredDraft("s1", "");
    expect(localStorage.getItem("coworker:composer-draft:v1:s1")).toBeNull();
    expect(readStoredDraft("s1")).toBeUndefined();
    writeStoredDraft("", "stray");
    expect(localStorage.length).toBe(0);
    expect(readStoredDraft("")).toBeUndefined();
  });

  it("a throwing localStorage (private mode, quota) is swallowed on both read and write", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(() => writeStoredDraft("s1", "half a thought")).not.toThrow();
    expect(readStoredDraft("s1")).toBeUndefined();
  });
});
