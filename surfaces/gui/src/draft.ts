import type { Item } from "./types";
// A conversation has started once the transcript holds anything beyond mode bookkeeping (the
// Auto-approve banner / mode markers record a setting, not activity — owner ask 2026-09-02).
// Until then the session is a draft: the setup row stays, the model stays choosable, the header
// states no facts.
export function hasConversation(items: Item[]): boolean {
  return items.some((i) => !(i.kind === "notice" && i.bookkeeping));
}
