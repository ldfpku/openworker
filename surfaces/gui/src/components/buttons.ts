// The text-button class strings, in one place. Twelve files used to each define their own
// BTN_ACCENT / BTN_BORDERED with slightly different sizes (12 vs 13px, py-1.5 vs py-2,
// with and without disabled:opacity) — same intent, drifting looks. Two sizes, four intents:
//
//   BTN_ACCENT / BTN_BORDERED        — the default (13px) pair for page-level actions
//   BTN_ACCENT_SM / BTN_BORDERED_SM  — the compact (12px) pair for rail rows and dense cards
//   BTN_OUTLINE / BTN_OUTLINE_SM     — accent-outlined secondary ("Approve once", "Sign in")
//   BTN_DANGER_SM                    — bordered, red text: the destructive row action ("Delete")
//   BTN_QUIET                        — text-only destructive-ish action ("Dismiss", "Deny")
//   BTN_SKIP                         — text-only escape that is not a rejection ("Skip" a question)
//
// Icon-only buttons are a component, not a class string: see IconButton.tsx.
// There is no CSS button family any more (the old `.btn` / `.btn-primary` / connector
// PILL_* strings were folded in here 2026-09-03); do not add text-button classes elsewhere.

export const BTN_ACCENT =
  "text-[13px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";
export const BTN_BORDERED =
  "text-[13px] px-3 py-2 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0 disabled:opacity-40 disabled:hover:border-line";

export const BTN_ACCENT_SM =
  "text-[12px] px-2.5 py-1.5 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";
export const BTN_BORDERED_SM =
  "text-[12px] px-2.5 py-1.5 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0 disabled:opacity-40 disabled:hover:border-line";

export const BTN_OUTLINE =
  "text-[13px] px-3 py-2 rounded-lg border border-accent text-accent font-medium hover:bg-accentSoft shrink-0 disabled:opacity-40";
export const BTN_OUTLINE_SM =
  "text-[12px] px-2.5 py-1.5 rounded-lg border border-accent text-accent font-medium hover:bg-accentSoft shrink-0 disabled:opacity-40";
export const BTN_DANGER_SM =
  "text-[12px] px-2.5 py-1.5 rounded-lg border border-line bg-paper text-danger hover:border-danger shrink-0 disabled:opacity-40";
export const BTN_QUIET = "text-[13px] px-3 py-2 text-faint hover:text-danger shrink-0";
// Skip (OPE-153) is an escape, not a rejection — quiet like Deny, without the danger red. Uses
// `muted` rather than Deny's `faint`: a borderless text button is already secondary next to the
// option pills, and this one has to be FOUND (faint is only ~3:1 on the dark panel).
export const BTN_SKIP = "text-[13px] px-3 py-2 text-muted hover:text-ink shrink-0";
