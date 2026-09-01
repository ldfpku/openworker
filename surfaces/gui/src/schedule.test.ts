import { describe, expect, it } from "vitest";
import { FREQ_OPTIONS, fromCron, toCron } from "./schedule";

describe("schedule cron round-trip", () => {
  it("round-trips every frequency option", () => {
    for (const { key } of FREQ_OPTIONS) {
      const cron = toCron("07:30", key);
      expect(fromCron(cron)).toEqual({ time: "07:30", freq: key, matched: true });
    }
  });

  it("parses a single-day cron instead of collapsing it to daily (the Monday-template bug)", () => {
    expect(fromCron("30 8 * * 1")).toEqual({ time: "08:30", freq: "mon", matched: true });
    expect(fromCron("30 16 * * 5")).toEqual({ time: "16:30", freq: "fri", matched: true });
  });

  it("keeps recognizing the legacy weekday/weekend/daily forms", () => {
    expect(fromCron("0 9 * * 1-5")).toEqual({ time: "09:00", freq: "weekdays", matched: true });
    expect(fromCron("0 9 * * 0,6")).toEqual({ time: "09:00", freq: "weekends", matched: true });
    expect(fromCron("0 9 * * 6,0")).toEqual({ time: "09:00", freq: "weekends", matched: true });
    expect(fromCron("0 9 * * *")).toEqual({ time: "09:00", freq: "daily", matched: true });
  });

  it("accepts cron's alternate Sunday (7) and midnight hours", () => {
    expect(fromCron("0 9 * * 7")).toEqual({ time: "09:00", freq: "sun", matched: true });
    expect(fromCron("0 0 * * *")).toEqual({ time: "00:00", freq: "daily", matched: true });
  });

  it("flags crons the simple form can't express, with a best-effort prefill", () => {
    expect(fromCron("*/15 * * * *").matched).toBe(false); // step minutes
    expect(fromCron("30 8 1 * *").matched).toBe(false); // day-of-month schedule
    expect(fromCron("30 8 * 6 *").matched).toBe(false); // month-bound schedule
    expect(fromCron("30 8 * * 1,3").matched).toBe(false); // dow list
    expect(fromCron("30 8 1 * *")).toMatchObject({ time: "08:30", freq: "daily" });
  });

  it("falls back safely on missing or malformed input", () => {
    expect(fromCron(undefined)).toEqual({ time: "09:00", freq: "daily", matched: false });
    expect(fromCron(null)).toEqual({ time: "09:00", freq: "daily", matched: false });
    expect(fromCron("not a cron")).toEqual({ time: "09:00", freq: "daily", matched: false });
  });

  it("writes midnight and unknown keys defensively", () => {
    expect(toCron("00:15", "wed")).toBe("15 0 * * 3");
    expect(toCron("09:00", "bogus")).toBe("0 9 * * *");
  });
});
