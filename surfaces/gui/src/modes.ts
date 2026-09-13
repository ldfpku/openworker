/**
 * One permission-mode vocabulary for the whole GUI.
 *
 * The server's `Mode` enum (coworker/permissions.py) is the wire vocabulary, and it is
 * CANONICAL in everything the server emits: the "ready" frame, persisted session records and
 * persona manifests all carry `discuss` / `plan` / `interactive` / `custom` / `auto-approve` /
 * `bypass-approvals`. The single exception is `"auto"`, the pre-2026-08-12 spelling of
 * bypass-approvals: `Mode._missing_` still ACCEPTS it on input (old configs and saved
 * sessions), but nothing ever sends it back.
 *
 * Audit 2026-09-13: the client had drifted the other way — the composer's picker knew only
 * the legacy `"auto"`, so any session that reported the canonical value (anything started from
 * the CLI/TUI, or simply reconnected) matched no option row: the chip showed the raw
 * `bypass-approvals`, the ✓ and the selected-row highlight vanished, and the gated
 * Auto-approve escape hatch stopped recognising the current mode. Meanwhile PersonaPeek kept
 * its own private lookup table that DID know the canonical spelling. Hence this module: every
 * inbound mode is normalised here once, every outbound mode is canonical, and one table owns
 * the labels so the picker, the persona pages and the gallery can never name a mode
 * differently again.
 */

/** Legacy `"auto"` -> the canonical `"bypass-approvals"`; every other value passes through
 *  untouched (including values this client does not know — the server owns the vocabulary). */
export function normalizeMode(v: string): string {
  return v === "auto" ? "bypass-approvals" : v;
}

/** Canonical mode -> its i18n label key. Canonical spellings only: normalise before looking
 *  up (`modeLabel` does). `bypass-approvals` keeps the historical `composer.mode.auto` key —
 *  the locale key is not the wire value, and renaming it would churn both catalogs. */
export const MODE_KEYS: Record<string, string> = {
  discuss: "composer.mode.discuss",
  plan: "composer.mode.plan",
  interactive: "composer.mode.interactive",
  custom: "composer.mode.custom",
  "auto-approve": "composer.mode.auto_approve",
  "bypass-approvals": "composer.mode.auto",
};

/** The user-facing name of a mode, in the words the composer's picker uses. An unknown value
 *  renders as itself — a raw id is ugly but honest, and better than hiding a mode the server
 *  added and this build has never heard of. */
export function modeLabel(t: (key: string) => string, v: string): string {
  const key = MODE_KEYS[normalizeMode(v)];
  return key ? t(key) : v;
}
