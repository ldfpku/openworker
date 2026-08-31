/**
 * i18n initialization (react-i18next).
 *
 * Locale resources live in src/locales/*.json. English is the default and
 * fallback; the language follows the system locale unless the user picks one
 * explicitly in Settings (persisted in localStorage).
 */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en.json";
import zh from "./locales/zh.json";
// The fork's original catalog, keyed by the English source string itself. Upstream later
// built its own scheme (dotted keys + en/zh.json) and we adopted it in the 2026-08-31 merge,
// but ~200 call sites still live in fork-only files (the Expert library, the in-app manual,
// the Gemini/Gateway sign-in panes, the WeChat QR pane) where English-as-key costs nothing —
// upstream has no such files, so they can never conflict. Keeping this catalog loaded means
// those keep rendering Chinese instead of silently falling back to their English key.
import zhLegacy from "./locales/zh-CN.json";

const STORAGE_KEY = "openworker.lang";

export const SUPPORTED_LANGS = ["en", "zh"] as const;
export type Lang = (typeof SUPPORTED_LANGS)[number];

/** The user's explicit choice wins; otherwise follow the system locale. */
function resolveLang(): Lang {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && (SUPPORTED_LANGS as readonly string[]).includes(stored)) {
      return stored as Lang;
    }
  } catch {
    /* localStorage unavailable — fall through to system locale */
  }
  const nav = (typeof navigator !== "undefined" && navigator.language) || "";
  return nav.toLowerCase().startsWith("zh") ? "zh" : "en";
}

/** Nested catalog -> flat dotted keys, so lookups can run with keySeparator disabled. */
function flatten(obj: Record<string, unknown>, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      Object.assign(out, flatten(v as Record<string, unknown>, key));
    } else if (typeof v === "string") {
      out[key] = v;
    }
  }
  return out;
}

export async function initI18n() {
  // Both key styles have to resolve from one catalog: upstream's "nav.settings" and the
  // fork's "Note: Google Workspace and Microsoft 365 accounts…". The latter is full of dots
  // and colons, which i18next would otherwise read as path and namespace separators — so we
  // flatten upstream's nesting up front and turn both separators off, making every lookup a
  // literal key match.
  await i18n.use(initReactI18next).init({
    keySeparator: false,
    nsSeparator: false,
    resources: {
      en: { translation: flatten(en as Record<string, unknown>) },
      zh: { translation: { ...zhLegacy, ...flatten(zh as Record<string, unknown>) } },
    },
    lng: resolveLang(),
    fallbackLng: "en",
    interpolation: { escapeValue: false }, // React already escapes
    returnNull: false,
  });
  return i18n;
}

/** Switch language at runtime and persist the choice. Pass null to follow the system locale again. */
export function setLanguage(lang: Lang | null) {
  try {
    if (lang === null) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* persistence failure shouldn't block the switch */
  }
  return i18n.changeLanguage(lang ?? resolveLang());
}

/** The user's persisted choice, or null when following the system locale. */
export function getStoredLanguage(): Lang | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && (SUPPORTED_LANGS as readonly string[]).includes(stored)) {
      return stored as Lang;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function getCurrentLanguage(): Lang {
  const l = i18n.language;
  return (l && l.startsWith("zh") ? "zh" : "en") as Lang;
}

// Fork-only surfaces (LibraryView, the manual, the sign-in panes) import the instance
// directly to read i18n.language when choosing a bundled zh asset.
export default i18n;
