// A refused persona write has to say WHY, in the user's language. The server's own message
// is English prose, so the refusal carries a stable machine code and the UI translates on
// that — with the prose kept as the fallback for anything the catalog does not know yet
// (audit 2026-09-13).
import { describe, expect, it } from "vitest";
import { personaErrorText } from "./personaErrors";
import en from "./locales/en.json";

// A stand-in for i18next's `t`: resolves "a.b" against the real English catalog, so the test
// pins the actual keys rather than a mock's idea of them.
const t = ((key: string) =>
  key.split(".").reduce<any>((node, k) => node?.[k], en as any) ?? key) as any;

describe("personaErrorText", () => {
  it("translates a known refusal code and ignores the server's English", () => {
    expect(
      personaErrorText({ code: "baseline_locked", error: "the general coworker is…" }, t),
    ).toBe(en.personas.refused_baseline_locked);
    expect(personaErrorText({ code: "default_locked", error: "x" }, t)).toBe(
      en.personas.refused_default_locked,
    );
    expect(personaErrorText({ code: "unknown_persona", error: "x" }, t)).toBe(
      en.personas.refused_unknown_persona,
    );
  });

  it("falls back to the server's words for a code this build has never heard of", () => {
    // A newer sidecar refusing for a new reason must still explain itself — specific
    // English beats a generic localized shrug.
    expect(personaErrorText({ code: "invented_later", error: "nope, not allowed" }, t)).toBe(
      "nope, not allowed",
    );
    expect(personaErrorText({ error: "nope, not allowed" }, t)).toBe("nope, not allowed");
  });

  it("falls back to the generic line when the server said nothing at all", () => {
    expect(personaErrorText({}, t)).toBe(en.personas.update_failed);
    expect(personaErrorText({}, t, "persona.load_error")).toBe(en.persona.load_error);
  });
});
