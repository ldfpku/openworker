// Shared vitest setup: mirror the app boot (main.tsx calls initI18n() pre-render) so
// react-i18next is initialized before any component renders in tests. jsdom's navigator
// language is en-US, English strings ARE the i18next keys, and the en catalog is empty,
// so English output stays byte-identical — this only makes t() interpolate placeholders
// ({{n}}, {{version}}, …) exactly as it does in the running app.
import { initI18n } from "./i18n";

// Awaited: initI18n is async now (it was a sync initLocale before the upstream merge), and a
// fire-and-forget call let components render before the catalogs loaded — t() then returned
// the raw key, which only shows up in the zh assertions.
await initI18n();
