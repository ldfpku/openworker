// Shared vitest setup: mirror the app boot (main.tsx calls initLocale() pre-render) so
// react-i18next is initialized before any component renders in tests. jsdom's navigator
// language is en-US, English strings ARE the i18next keys, and the en catalog is empty,
// so English output stays byte-identical — this only makes t() interpolate placeholders
// ({{n}}, {{version}}, …) exactly as it does in the running app.
import { initLocale } from "./i18n";

initLocale();
