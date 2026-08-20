import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { getLocalePref, initLocale, resolveLocale, setLocalePref } from "./i18n";

const KEY = "openwork-locale";

// setLocalePref() calls i18n.changeLanguage(), so i18next must be initialized before any
// test runs — in the app this is guaranteed by main.tsx calling initLocale() pre-render.
beforeAll(() => {
  initLocale();
});

afterEach(() => {
  localStorage.removeItem(KEY);
  vi.unstubAllGlobals();
});

describe("resolveLocale", () => {
  it("auto follows a zh navigator language", () => {
    vi.stubGlobal("navigator", { language: "zh-CN" });
    expect(resolveLocale("auto")).toBe("zh-CN");
  });

  it("auto falls back to en for a non-zh navigator language", () => {
    vi.stubGlobal("navigator", { language: "en-US" });
    expect(resolveLocale("auto")).toBe("en");
  });

  it("an explicit pref wins over the navigator language", () => {
    vi.stubGlobal("navigator", { language: "zh-CN" });
    expect(resolveLocale("en")).toBe("en");
    vi.stubGlobal("navigator", { language: "en-US" });
    expect(resolveLocale("zh-CN")).toBe("zh-CN");
  });
});

describe("getLocalePref / setLocalePref", () => {
  it("defaults to auto, and an explicit choice persists", () => {
    expect(getLocalePref()).toBe("auto");
    setLocalePref("zh-CN");
    expect(getLocalePref()).toBe("zh-CN");
    expect(localStorage.getItem(KEY)).toBe("zh-CN");
  });

  it("auto clears the stored key rather than writing 'auto'", () => {
    setLocalePref("en");
    setLocalePref("auto");
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(getLocalePref()).toBe("auto");
  });
});

describe("t()", () => {
  beforeEach(() => {
    initLocale();
  });

  it("returns the key verbatim when zh-CN has no matching entry — the en fallback", () => {
    i18n.changeLanguage("zh-CN");
    expect(i18n.t("No such catalog entry, obviously")).toBe("No such catalog entry, obviously");
  });

  it("returns the zh-CN value once the catalog has an entry for the key", () => {
    // Inject directly rather than editing locales/zh-CN.json — that file is populated by a
    // later translation pass, not this test.
    i18n.addResource("zh-CN", "translation", "Settings", "设置");
    i18n.changeLanguage("zh-CN");
    expect(i18n.t("Settings")).toBe("设置");
  });
});
