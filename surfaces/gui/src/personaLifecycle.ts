import type { Persona } from "./api";

/**
 * The BASELINE coworker: the general OpenWorker. The server (coworker/personas/registry.py)
 * guarantees it is always enabled — it is the fallback for new sessions, inbound DMs and for
 * every persona that gets switched off, so nothing can disable it.
 *
 * The ONE declaration of the id: every surface that treats the general coworker specially
 * (the setup row, the personas list, a persona's detail page, the scope labels) imports it
 * from here. This module is plain TypeScript — no React — so a component importing it costs
 * nothing, while a second copy could drift and half the surfaces would keep offering a
 * switch the server refuses (audit 2026-09-13).
 */
export const BASELINE_PERSONA = "cowork";

/**
 * Which coworker should the app fall back to, given the one it is currently on?
 *
 * This REPAIRS an impossible state — the active persona was switched off in Settings, or a
 * resumed session landed on one that no longer runs — and nothing else. It never second-guesses
 * a deliberate pick: an agent that is enabled, or that this persona list has never heard of,
 * returns `null` ("leave it alone"). `null` for the baseline too: it cannot be disabled, so a
 * prefs file that claims otherwise is the stale thing, not the pick. That case is not
 * theoretical — a `cowork: false` left in prefs used to bounce the setup row's "use a
 * specialist" switch straight back on every launch (audit 2026-09-13; the server now self-heals
 * such an entry, this is the client half).
 *
 * The repair target is the CONFIGURED default coworker — what new sessions and inbound DMs
 * use — and only if that one is itself enabled; otherwise the baseline, which always is.
 */
export function fallbackAgent(agent: string, personas: Persona[] | null): string | null {
  if (agent === BASELINE_PERSONA) return null; // always available; never repaired away from
  const list = personas || [];
  const active = list.find((p) => p.id === agent);
  if (!active) return null; // unknown to this list (not loaded yet, or a persona we can't judge)
  if (active.enabled) return null; // a live coworker: this is a pick, not a broken state
  return list.find((p) => p.default && p.enabled)?.id || BASELINE_PERSONA;
}
