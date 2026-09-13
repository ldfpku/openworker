/**
 * Who wins when the user's model/mode pick and the server's report of the same setting
 * disagree — the acknowledgement protocol (audit 2026-09-13).
 *
 * The GUI holds `model` and `mode` as local state and the server holds them as engine truth.
 * Every reconnect opens with a `ready` frame that reports both, and the client used to apply
 * them unconditionally: pick "Plan" (or a different model) while a reconnect was in flight —
 * a coworker switch, a folder pick, any `connectNonce` bump — and `ready` reverted the pick a
 * beat later, with nothing on screen to explain it.
 *
 * So a hand pick is AUTHORITATIVE until the server acknowledges it. An outstanding pick is
 * "pending"; `ready` may not overwrite a key that has one, and the pick is re-sent on every
 * new socket (a pick typed at a socket that was already tearing down never reached the server
 * at all). Acknowledgement comes as an echo — `model_changed` / `mode_changed` — or as a
 * `ready` that already reports the picked value.
 *
 * Picks are scoped to one session id: switching sessions replaces the whole record, so a pick
 * can never leak onto the conversation the user moved to.
 */

export type PickKey = "model" | "mode";

export type PendingPicks = {
  sessionId: string;
  model?: string;
  mode?: string;
};

/** The outstanding pick for `key`, but only if it belongs to `sessionId`. */
export function pendingFor(cur: PendingPicks, sessionId: string, key: PickKey): string | undefined {
  return cur.sessionId === sessionId ? cur[key] : undefined;
}

/** Remember a pick we are about to send. A pick for a different session replaces the record
 *  wholesale — the previous session's outstanding picks are no longer ours to assert. */
export function recordPick(
  cur: PendingPicks,
  sessionId: string,
  key: PickKey,
  value: string,
): PendingPicks {
  const base: PendingPicks = cur.sessionId === sessionId ? { ...cur } : { sessionId };
  base[key] = value;
  return base;
}

/** Forget the outstanding pick for `key` (it has been acknowledged). */
export function clearPick(cur: PendingPicks, key: PickKey): PendingPicks {
  if (cur[key] === undefined) return cur;
  const next = { ...cur };
  delete next[key];
  return next;
}

/**
 * Reconcile ONE setting reported by a `ready` frame against the pick that may still be in
 * flight. `ready` is a snapshot taken as the socket opened, so it can easily predate a pick
 * this client made on the socket before it — it may not clobber one.
 *
 * `apply` is the value to write into React state (null = leave state alone); `clearPending`
 * says the server has now confirmed the pick, so stop asserting it.
 *
 * An ECHO (`model_changed` / `mode_changed`) is deliberately NOT run through this: an echo is
 * the server speaking about this key rather than merely opening a connection, so it always
 * wins and always clears the pick — otherwise a pick the server declined (or overrode) would
 * stay pending forever and the chip would keep showing a value the engine never adopted.
 */
export function reconcileSetting(
  pending: string | undefined,
  incoming: string | undefined,
): { apply: string | null; clearPending: boolean } {
  if (!incoming) return { apply: null, clearPending: false }; // the frame said nothing
  if (pending === undefined) return { apply: incoming, clearPending: false };
  if (pending === incoming) return { apply: incoming, clearPending: true }; // acknowledged
  return { apply: null, clearPending: false }; // our pick stands, and stays outstanding
}
