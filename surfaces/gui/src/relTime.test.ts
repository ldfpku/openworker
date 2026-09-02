import { describe, expect, it } from "vitest";
import { formatRelative } from "./relTime";

// A stub translator that echoes the key and count — the ladder and the style routing are
// what's under test, not the catalogs (those are exercised by the component tests).
const t = (key: string, opts?: Record<string, unknown>) =>
  opts && "count" in opts ? `${key}:${opts.count}` : key;
const NOW = 1_800_000_000_000; // ms
const ago = (ms: number) => (NOW - ms) / 1000; // → epoch seconds

describe("formatRelative", () => {
  it("walks the ladder: just now → minutes → hours → days → weeks → months → years", () => {
    expect(formatRelative(ago(10_000), t, { now: NOW })).toBe("time.long.just_now");
    expect(formatRelative(ago(5 * 60_000), t, { now: NOW })).toBe("time.long.minutes_ago:5");
    expect(formatRelative(ago(2 * 3_600_000), t, { now: NOW })).toBe("time.long.hours_ago:2");
    expect(formatRelative(ago(3 * 86_400_000), t, { now: NOW })).toBe("time.long.days_ago:3");
    expect(formatRelative(ago(15 * 86_400_000), t, { now: NOW })).toBe("time.long.weeks_ago:2");
    expect(formatRelative(ago(100 * 86_400_000), t, { now: NOW })).toBe("time.long.months_ago:3");
    expect(formatRelative(ago(800 * 86_400_000), t, { now: NOW })).toBe("time.long.years_ago:2");
  });

  it("rounds instead of flooring, and never says 60 minutes / 24 hours", () => {
    expect(formatRelative(ago(59.6 * 60_000), t, { now: NOW })).toBe("time.long.hours_ago:1");
    expect(formatRelative(ago(23.7 * 3_600_000), t, { now: NOW })).toBe("time.long.days_ago:1");
    expect(formatRelative(ago(364 * 86_400_000), t, { now: NOW })).toBe("time.long.months_ago:11");
  });

  it("routes to the requested style's keys", () => {
    expect(formatRelative(ago(5 * 60_000), t, { now: NOW, style: "short" })).toBe("time.short.minutes_ago:5");
    expect(formatRelative(ago(5 * 60_000), t, { now: NOW, style: "compact" })).toBe("time.compact.minutes_ago:5");
  });

  it("accepts an ISO string, and treats a future stamp as just now", () => {
    const iso = new Date(NOW - 6 * 3_600_000).toISOString();
    expect(formatRelative(iso, t, { now: NOW, style: "compact" })).toBe("time.compact.hours_ago:6");
    expect(formatRelative(ago(-30_000), t, { now: NOW })).toBe("time.long.just_now");
  });

  it("renders nothing for a missing or unparseable stamp", () => {
    expect(formatRelative(undefined, t)).toBe("");
    expect(formatRelative(null, t)).toBe("");
    expect(formatRelative(0, t)).toBe("");
    expect(formatRelative("not a date", t)).toBe("");
    expect(formatRelative(NaN, t)).toBe("");
  });
});
