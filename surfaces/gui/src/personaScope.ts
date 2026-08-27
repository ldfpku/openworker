import i18n from "./i18n";

// A persona is "project-scoped" when it declares requires_folder: an explicit directory the
// user picks, sessions grouped by project in the sidebar. Everything else runs on a transparent
// per-conversation scratch dir, with real folders added as roots when needed — no folder gate.
// (The old family/workspace-enum pair collapsed into this trait; workspace-scratch-design.md.)
export function isProjectScoped(p?: { requires_folder?: boolean }): boolean {
  return p?.requires_folder === true;
}

// Persona naming: the product is "OpenWorker"; the personas are a "Coworker" family — Coworker
// (general), Code Coworker, Ops Coworker. In lists/chrome we use the SHORT label (Coworker / Code /
// Ops); the persona detail page uses the FULL family name. Backend names are left untouched (the
// API + tests keep "OpenWorker" / "Ops Coworker"); this is purely the display layer.

// Short label for the sidebar + top bar: "Coworker" / "Code" / "Ops" / "Chat".
// Both helpers run the raw backend name through i18n so builtin personas localize like any
// other UI string (English key falls through untouched — same word-list mechanism as
// Sidebar's t(p.name)).
export function shortPersonaName(name?: string, id?: string): string {
  if (id === "cowork") return i18n.t("Coworker");
  const n = (name || id || "").trim();
  return i18n.t(n.replace(/\s*coworker$/i, "").trim() || n);
}

// Full family name for the persona detail page: "Coworker" / "Code Coworker" / "Ops Coworker".
// Chat isn't a coworker — left as-is. The " Coworker" suffix goes through a template key so
// zh can drop it ("专家团队长 Coworker" read as noise; the zh entry is just "{{name}}").
export function fullPersonaName(name?: string, id?: string): string {
  if (id === "cowork") return i18n.t("Coworker");
  const n = (name || id || "").trim();
  if (id === "chat" || !n) return n;
  return /coworker$/i.test(n) ? i18n.t(n) : i18n.t("{{name}} Coworker", { name: i18n.t(n) });
}
