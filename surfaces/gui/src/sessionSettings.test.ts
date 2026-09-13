// The model/mode acknowledgement protocol: a hand pick outranks the server's `ready` report
// until the server acknowledges it (audit 2026-09-13).
import { describe, expect, it } from "vitest";
import { clearPick, pendingFor, recordPick, reconcileSetting, type PendingPicks } from "./sessionSettings";
import { normalizeMode } from "./modes";

describe("pending picks bookkeeping", () => {
  it("records and reads a pick for the current session", () => {
    let picks: PendingPicks = { sessionId: "s1" };
    picks = recordPick(picks, "s1", "mode", "plan");
    expect(pendingFor(picks, "s1", "mode")).toBe("plan");
    expect(pendingFor(picks, "s1", "model")).toBeUndefined();
  });

  it("keeps model and mode independent", () => {
    let picks: PendingPicks = { sessionId: "s1" };
    picks = recordPick(picks, "s1", "mode", "plan");
    picks = recordPick(picks, "s1", "model", "gpt-5.6-sol");
    expect(picks).toEqual({ sessionId: "s1", mode: "plan", model: "gpt-5.6-sol" });
    expect(pendingFor(clearPick(picks, "mode"), "s1", "model")).toBe("gpt-5.6-sol");
  });

  it("drops the previous session's picks when the session changes", () => {
    let picks: PendingPicks = { sessionId: "s1", mode: "plan", model: "m1" };
    picks = recordPick(picks, "s2", "mode", "discuss");
    expect(picks).toEqual({ sessionId: "s2", mode: "discuss" });
    // and a pick left over from another session is never asserted against this one
    expect(pendingFor({ sessionId: "s1", mode: "plan" }, "s2", "mode")).toBeUndefined();
  });

  it("clearing an absent pick is a no-op (same object, no churn)", () => {
    const picks: PendingPicks = { sessionId: "s1" };
    expect(clearPick(picks, "model")).toBe(picks);
  });
});

describe("reconcileSetting (a `ready` frame vs an outstanding pick)", () => {
  it("applies the server value when nothing is pending", () => {
    expect(reconcileSetting(undefined, "plan")).toEqual({ apply: "plan", clearPending: false });
  });

  it("ignores a frame that reports nothing for the key", () => {
    expect(reconcileSetting(undefined, undefined)).toEqual({ apply: null, clearPending: false });
    expect(reconcileSetting("plan", "")).toEqual({ apply: null, clearPending: false });
  });

  it("keeps the pick when the server still reports the old value", () => {
    // The reconnect's snapshot predates the pick — this is exactly the revert that was
    // happening: pick Plan, socket reconnects, `ready` says interactive.
    expect(reconcileSetting("plan", "interactive")).toEqual({ apply: null, clearPending: false });
  });

  it("treats a `ready` that already reports the picked value as the acknowledgement", () => {
    expect(reconcileSetting("plan", "plan")).toEqual({ apply: "plan", clearPending: true });
  });

  it("acknowledges the legacy spelling once it has been normalised (C4)", () => {
    // The picker sends the canonical `bypass-approvals`; a session persisted before
    // 2026-08-12 reports `auto`. Normalised first, these are the same mode.
    const pending = normalizeMode("bypass-approvals");
    expect(reconcileSetting(pending, normalizeMode("auto"))).toEqual({
      apply: "bypass-approvals",
      clearPending: true,
    });
  });
});
