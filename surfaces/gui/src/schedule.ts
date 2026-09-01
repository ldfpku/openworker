// The Automations surfaces' shared simple-schedule vocabulary: ONE list of frequency
// choices (daily / weekdays / weekends / single days) used by both the quickstart's
// "When" menu and the editor's "Repeat" selects, plus the cron round-trip between them.
// Before this existed the editor only knew daily/weekdays/weekends, so editing a
// single-day automation (e.g. a Monday template) silently rewrote it to daily.

export interface FreqOption {
  key: string;
  labelKey: string; // i18n key — resolved via t() at the render site
  dow: string; // the cron day-of-week field this choice writes
}

export const FREQ_OPTIONS: FreqOption[] = [
  { key: "daily", labelKey: "automations.freq_daily", dow: "*" },
  { key: "weekdays", labelKey: "automations.freq_weekdays", dow: "1-5" },
  { key: "weekends", labelKey: "automations.freq_weekends", dow: "0,6" },
  { key: "mon", labelKey: "automations.day_mon", dow: "1" },
  { key: "tue", labelKey: "automations.day_tue", dow: "2" },
  { key: "wed", labelKey: "automations.day_wed", dow: "3" },
  { key: "thu", labelKey: "automations.day_thu", dow: "4" },
  { key: "fri", labelKey: "automations.day_fri", dow: "5" },
  { key: "sat", labelKey: "automations.day_sat", dow: "6" },
  { key: "sun", labelKey: "automations.day_sun", dow: "0" },
];

const DOW_BY_KEY = new Map(FREQ_OPTIONS.map((o) => [o.key, o.dow]));
const KEY_BY_DOW = new Map(FREQ_OPTIONS.map((o) => [o.dow, o.key]));
KEY_BY_DOW.set("6,0", "weekends"); // order-insensitive
KEY_BY_DOW.set("7", "sun"); // cron allows 0 and 7 for Sunday

// Map a time-of-day + frequency selection to a 5-field cron string.
export function toCron(time: string, freq: string): string {
  const [h, m] = (time || "09:00").split(":").map((x) => parseInt(x, 10) || 0);
  return `${m} ${h} * * ${DOW_BY_KEY.get(freq) ?? "*"}`;
}

// Parse a simple "min hour * * dow" cron back into the editor's time + frequency.
// `matched: false` means the cron says something these options can't express
// (agent-written steps, day-of-month schedules, dow lists…) — time/freq are then a
// best-effort prefill, and saving the edit form would REWRITE the schedule, so the
// editor must warn before letting that happen silently.
export function fromCron(cron?: string | null): { time: string; freq: string; matched: boolean } {
  const parts = (cron || "").trim().split(/\s+/);
  if (parts.length !== 5) return { time: "09:00", freq: "daily", matched: false };
  const [m, h, dom, mon, dow] = parts;
  const mn = parseInt(m, 10);
  const hn = parseInt(h, 10);
  const hh = String(Math.min(23, Math.max(0, Number.isNaN(hn) ? 9 : hn))).padStart(2, "0");
  const mm = String(Math.min(59, Math.max(0, Number.isNaN(mn) ? 0 : mn))).padStart(2, "0");
  const freq = KEY_BY_DOW.get(dow);
  const matched =
    freq !== undefined &&
    dom === "*" &&
    mon === "*" &&
    /^\d+$/.test(m) &&
    /^\d+$/.test(h) &&
    mn <= 59 &&
    hn <= 23;
  return { time: `${hh}:${mm}`, freq: freq ?? "daily", matched };
}
