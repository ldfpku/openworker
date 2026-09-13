// One mode vocabulary (audit 2026-09-13): the server emits canonical Mode values and still
// accepts the legacy "auto", so the client has to read both and write only the canonical one.
import { describe, expect, it } from "vitest";
import { MODE_KEYS, modeLabel, normalizeMode } from "./modes";

// A stand-in for i18next's t(): returns the key, so the assertions pin down WHICH key each
// mode resolves to without depending on the catalogs' current wording.
const key = (k: string) => k;

describe("normalizeMode", () => {
  it("folds the legacy 'auto' into the canonical 'bypass-approvals'", () => {
    expect(normalizeMode("auto")).toBe("bypass-approvals");
  });

  it("leaves every canonical value untouched", () => {
    for (const v of [
      "discuss",
      "plan",
      "interactive",
      "custom",
      "auto-approve",
      "bypass-approvals",
    ]) {
      expect(normalizeMode(v)).toBe(v);
    }
  });

  it("passes an unknown value through rather than guessing", () => {
    expect(normalizeMode("some-future-mode")).toBe("some-future-mode");
    expect(normalizeMode("")).toBe("");
  });
});

describe("modeLabel", () => {
  it("labels both spellings of bypass-approvals identically", () => {
    expect(modeLabel(key, "bypass-approvals")).toBe("composer.mode.auto");
    expect(modeLabel(key, "auto")).toBe("composer.mode.auto");
  });

  it("labels the modes the picker doesn't offer", () => {
    expect(modeLabel(key, "plan")).toBe("composer.mode.plan");
    expect(modeLabel(key, "custom")).toBe("composer.mode.custom");
  });

  it("labels the offered modes", () => {
    expect(modeLabel(key, "discuss")).toBe("composer.mode.discuss");
    expect(modeLabel(key, "interactive")).toBe("composer.mode.interactive");
    expect(modeLabel(key, "auto-approve")).toBe("composer.mode.auto_approve");
  });

  it("falls back to the raw value for a mode this build has never heard of", () => {
    expect(modeLabel(key, "some-future-mode")).toBe("some-future-mode");
  });
});

describe("MODE_KEYS", () => {
  it("covers every value of the server's Mode enum, canonical spellings only", () => {
    expect(Object.keys(MODE_KEYS).sort()).toEqual([
      "auto-approve",
      "bypass-approvals",
      "custom",
      "discuss",
      "interactive",
      "plan",
    ]);
  });
});
