import type { TFunction } from "i18next";

/**
 * A refused persona write, said out loud in the user's language.
 *
 * The settings surfaces render a refusal inline next to the switch that bounced — never a
 * silent snap-back, which reads as a broken control. The server's own message is English
 * prose, and this app's primary UI is Chinese, so the refusals carry a stable machine `code`
 * (coworker/personas/registry.py: PersonaRefused) and the code is what we translate on.
 *
 * `error` stays the fallback, in this order: a known code → its localized string; an unknown
 * code with a message → the server's words, which are at least specific; nothing at all →
 * the generic failure line. One helper, used by every surface that shows one (audit
 * 2026-09-13).
 */
const KEYS: Record<string, string> = {
  baseline_locked: "personas.refused_baseline_locked",
  default_locked: "personas.refused_default_locked",
  unknown_persona: "personas.refused_unknown_persona",
};

export function personaErrorText(
  r: { code?: string; error?: string },
  t: TFunction,
  fallbackKey = "personas.update_failed",
): string {
  const key = r.code ? KEYS[r.code] : undefined;
  if (key) return t(key);
  return r.error || t(fallbackKey);
}
