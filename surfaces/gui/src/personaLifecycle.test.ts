// The disabled-coworker repair, truth table. It exists to rescue an impossible state and must
// never overrule a deliberate pick (audit 2026-09-13).
import { describe, expect, it } from "vitest";
import { BASELINE_PERSONA, fallbackAgent } from "./personaLifecycle";
import type { Persona } from "./api";

const persona = (id: string, over: Partial<Persona> = {}): Persona => ({
  id,
  name: id,
  icon: "",
  tagline: "",
  requires_folder: false,
  builtin: true,
  tools: [],
  enabled: true,
  surfaced: true,
  default: false,
  ...over,
});

describe("fallbackAgent", () => {
  it("leaves the baseline alone even when prefs claim it is disabled", () => {
    // The server forbids this state and self-heals it; the client must not act on a stale
    // prefs file either — it used to bounce "use a specialist" back on every launch.
    const personas = [persona(BASELINE_PERSONA, { enabled: false }), persona("scout")];
    expect(fallbackAgent(BASELINE_PERSONA, personas)).toBeNull();
  });

  it("leaves an enabled coworker alone", () => {
    expect(fallbackAgent("scout", [persona("scout"), persona(BASELINE_PERSONA)])).toBeNull();
  });

  it("leaves an agent the list has never heard of alone", () => {
    expect(fallbackAgent("ghost", [persona(BASELINE_PERSONA)])).toBeNull();
  });

  it("leaves everything alone while the persona list is still unloaded", () => {
    expect(fallbackAgent("scout", null)).toBeNull();
    expect(fallbackAgent("scout", [])).toBeNull();
  });

  it("repairs a disabled coworker onto the enabled default", () => {
    const personas = [
      persona(BASELINE_PERSONA),
      persona("scout", { enabled: false }),
      persona("analyst", { default: true }),
    ];
    expect(fallbackAgent("scout", personas)).toBe("analyst");
  });

  it("skips a default that is itself disabled and lands on the baseline", () => {
    const personas = [
      persona(BASELINE_PERSONA),
      persona("scout", { enabled: false }),
      persona("analyst", { default: true, enabled: false }),
    ];
    expect(fallbackAgent("scout", personas)).toBe(BASELINE_PERSONA);
  });

  it("falls back to the baseline when no persona holds the default pointer", () => {
    const personas = [persona(BASELINE_PERSONA), persona("scout", { enabled: false })];
    expect(fallbackAgent("scout", personas)).toBe(BASELINE_PERSONA);
  });
});
