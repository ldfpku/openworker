// Locale: English (default) or Chinese, picked from the system language or pinned by hand.
// Mirrors theme.ts's pref pattern exactly — same localStorage shape, same auto/explicit split.
// English strings ARE the i18next keys and the en catalog is never populated: a missing zh-CN
// entry falls back to the key itself, so English output is byte-identical whether or not this
// module ran (43 test files assert English literals — this guarantees they stay green).
import { useEffect, useState } from "react";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import zhCN from "./locales/zh-CN.json";

export type LocalePref = "auto" | "en" | "zh-CN";
export type Locale = "en" | "zh-CN";

const KEY = "openwork-locale";
const PREF_EVENT = "openwork:locale-pref";

export function getLocalePref(): LocalePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "en" || v === "zh-CN" ? v : "auto";
  } catch {
    return "auto";
  }
}

export function resolveLocale(pref: LocalePref): Locale {
  if (pref === "en" || pref === "zh-CN") return pref;
  return navigator.language.startsWith("zh") ? "zh-CN" : "en";
}

export function setLocalePref(pref: LocalePref) {
  try {
    if (pref === "auto") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, pref);
  } catch {
    /* private mode etc. — still applies for this session */
  }
  i18n.changeLanguage(resolveLocale(pref));
  window.dispatchEvent(new CustomEvent(PREF_EVENT));
}

/** Call once at startup, alongside initTheme(): wires up i18next and applies the stored pref. */
export function initLocale() {
  i18n.use(initReactI18next).init({
    resources: { "zh-CN": { translation: zhCN } },
    lng: resolveLocale(getLocalePref()),
    fallbackLng: "en",
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false }, // React already escapes.
  });
}

/** The settings control's hook — stays in sync if the pref changes elsewhere. */
export function useLocalePref(): [LocalePref, (p: LocalePref) => void] {
  const [pref, setPref] = useState<LocalePref>(getLocalePref);
  useEffect(() => {
    const sync = () => setPref(getLocalePref());
    window.addEventListener(PREF_EVENT, sync);
    return () => window.removeEventListener(PREF_EVENT, sync);
  }, []);
  return [pref, setLocalePref];
}

// Non-component modules translate via `import i18n from "./i18n"; i18n.t(...)`.
export default i18n;
