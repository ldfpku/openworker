import type { Item } from "./types";
// A conversation has started once the transcript holds anything beyond mode bookkeeping (the
// Auto-approve banner / mode markers record a setting, not activity — owner ask 2026-09-02).
// Until then the session is a draft: the setup row stays, the model stays choosable, the header
// states no facts.
export function hasConversation(items: Item[]): boolean {
  return items.some((i) => !(i.kind === "notice" && i.bookkeeping));
}

// The unsent composer text, per session, in localStorage — so a page reload hands it back
// (upstream f24b3fd4 / b90c02d5; the in-memory lift in App.tsx only covers a surface switch).
// Text only: attachments stay in memory, so no file contents or pasted documents are written
// to disk, and the restored draft carries `skill: null`. Best effort throughout — localStorage
// can be missing, full or blocked, and a draft is never worth an error.
const DRAFT_KEY_PREFIX = "coworker:composer-draft:v1:";

export function draftStorageKey(sessionId: string): string {
  return DRAFT_KEY_PREFIX + sessionId;
}

/** The saved text for this session, or undefined when there is none (never an empty draft:
 *  the composer seeds its prefill guard from the draft's presence). */
export function readStoredDraft(sessionId: string): string | undefined {
  if (!sessionId) return undefined;
  try {
    const text = localStorage.getItem(draftStorageKey(sessionId));
    return text ? text : undefined;
  } catch {
    return undefined;
  }
}

/** Mirror the box: non-empty text is saved, empty text (sent, cleared) removes the entry. */
export function writeStoredDraft(sessionId: string, text: string): void {
  if (!sessionId) return;
  try {
    const key = draftStorageKey(sessionId);
    if (text) localStorage.setItem(key, text);
    else localStorage.removeItem(key);
  } catch {
    /* best effort */
  }
}
