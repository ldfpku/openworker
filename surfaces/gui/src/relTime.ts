// The ONE relative-time formatter for the GUI (owner ruling 2026-09-02: five copies — providers,
// Manage tabs, connector cards, the sidebar and the transcript — collapsed into this module).
// Three output styles over one threshold ladder:
//   long     "5 minutes ago"   transcript answer footer
//   short    "5m ago"          provider / MCP / parked-message lists, connector cards
//   compact  "5m"              sidebar session rows
// Ladder: <45s → just now; then rounded minutes (<60), hours (<24), days (<7), weeks (<30d),
// months (<365d), years. Accepts epoch SECONDS (the server's `ts`) or an ISO string
// (`updated_at`). `now` is injectable — tests pin it, the Transcript shares one 30s ticker.

export type RelativeStyle = "long" | "short" | "compact";
export type Translate = (key: string, opts?: any) => string;

export function formatRelative(
  when: number | string | null | undefined,
  t: Translate,
  opts: { style?: RelativeStyle; now?: number } = {},
): string {
  const then =
    typeof when === "number" ? when * 1000 : typeof when === "string" && when ? Date.parse(when) : NaN;
  if (!Number.isFinite(then) || then <= 0) return "";
  const style = opts.style ?? "long";
  const say = (unit: string, count?: number) =>
    t(`time.${style}.${unit}`, count === undefined ? undefined : { count });
  const diff = Math.max(0, (opts.now ?? Date.now()) - then);
  if (diff < 45_000) return say("just_now");
  const mins = Math.round(diff / 60_000);
  if (mins < 60) return say("minutes_ago", mins);
  const hrs = Math.round(diff / 3_600_000);
  if (hrs < 24) return say("hours_ago", hrs);
  const days = Math.round(diff / 86_400_000);
  if (days < 7) return say("days_ago", days);
  if (days < 30) return say("weeks_ago", Math.min(4, Math.round(days / 7)));
  if (days < 365) return say("months_ago", Math.min(11, Math.max(1, Math.round(days / 30.4))));
  return say("years_ago", Math.max(1, Math.round(days / 365)));
}
