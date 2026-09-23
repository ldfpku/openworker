// One order for every model list in the app — provider checklists, the composer picker
// card, the composer dropdown, the summarizer select (owner call 2026-09-23): strictly by
// the model id string, DESCENDING, so the newest release leads (`gpt-6-sol` before
// `gpt-5.6-terra`, `claude-opus-5-5` before `claude-opus-5`). No pinning — the default is
// marked by its badge, not by position.
//
// "By string" with one refinement: runs of digits compare as numbers, so a two-digit
// version sorts where its number says (`gpt-5.10` above `gpt-5.9`; plain code-point order
// would put it below). Everything else is code-point order on the lowercased id; ties fall
// back to the raw id so the order is total and stable across renders.

const CHUNK = /\d+|\D+/g;

function compareAsc(a: string, b: string): number {
  const ca = a.toLowerCase().match(CHUNK) || [];
  const cb = b.toLowerCase().match(CHUNK) || [];
  const n = Math.min(ca.length, cb.length);
  for (let i = 0; i < n; i++) {
    const x = ca[i];
    const y = cb[i];
    if (x === y) continue;
    const xd = x.charCodeAt(0) >= 48 && x.charCodeAt(0) <= 57;
    const yd = y.charCodeAt(0) >= 48 && y.charCodeAt(0) <= 57;
    if (xd && yd) {
      const nx = Number(x);
      const ny = Number(y);
      if (nx !== ny) return nx < ny ? -1 : 1;
      if (x.length !== y.length) return x.length < y.length ? -1 : 1; // "08" vs "8"
      continue;
    }
    return x < y ? -1 : 1;
  }
  if (ca.length !== cb.length) return ca.length < cb.length ? -1 : 1;
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Comparator for `Array.prototype.sort`: newest-looking id first. */
export function compareModelIds(a: string, b: string): number {
  return compareAsc(b, a);
}

/** A sorted copy (never mutates the input — several lists come straight from state). */
export function sortModelIds(ids: readonly string[]): string[] {
  return [...ids].sort(compareModelIds);
}
