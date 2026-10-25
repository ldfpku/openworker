import { describe, expect, it } from "vitest";
import { wsReconnectDelay } from "./api";

// Session-socket reconnect backoff (status-display fix, 2026-10-26): the view used to
// stay frozen after any socket drop — the "finished / deadlocked" misread. The reconnect
// ladder lives here as a pure function so its shape is testable, not source-pinned.
describe("session-socket reconnect backoff", () => {
  it("starts at 500 ms and climbs to a 10 s ceiling", () => {
    for (const tries of [0, 1, 2, 3, 4, 5, 6, 7, 20]) {
      const base = Math.min(10000, 500 * 2 ** Math.max(0, tries));
      const d = wsReconnectDelay(tries);
      expect(d, `tries=${tries}`).toBeGreaterThanOrEqual(base);
      expect(d, `tries=${tries}`).toBeLessThan(base + 250);
    }
    expect(wsReconnectDelay(0)).toBeLessThan(1000); // first retry stays snappy
    expect(wsReconnectDelay(6)).toBeGreaterThanOrEqual(10000); // ceiling reached
    expect(wsReconnectDelay(99)).toBeLessThan(10250); // and stays there
  });

  it("jitters so a server restart does not bunch every window's retry together", () => {
    const seen = new Set<number>();
    for (let i = 0; i < 40; i++) seen.add(wsReconnectDelay(3));
    expect(seen.size).toBeGreaterThan(1);
  });
});
