// The in-app user manual (owner ask 2026-08-31): nine chapters of prose plus a card grid
// that doubles as navigation. Prose lives in Markdown files rather than the i18n catalog —
// a long Chinese manual split into hundreds of t() keys would swamp locales/zh-CN.json, and
// "the English string IS the key" is a poor fit for essay-length copy. Only the short
// chrome (card titles, blurbs, button labels) goes through t().
//
// Bodies load EAGERLY. A packaged build already burned us once on a lazy data-pack race, and
// ~40 KB of text is not worth a second helping of that class of bug.
import type { IconName } from "../components/Icon";

const BODIES = import.meta.glob("./zh-CN/*.md", {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;

// Settings' sub-nav keys (SettingsView's SetTab) that a chapter may deep-link to.
export type HelpSettingsTab =
  | "appearance"
  | "models"
  | "context"
  | "skills"
  | "voice"
  | "memory"
  | "personas";

// Full-page surfaces a chapter may deep-link to. Kept to the ones a reader would actually
// be sent to — App narrows this to its own surface union at the call site.
export type HelpSurface = "library" | "integrations" | "scheduled" | "inbox";

export type HelpAction =
  | { kind: "settings"; tab: HelpSettingsTab }
  | { kind: "surface"; to: HelpSurface }
  | { kind: "help"; chapter: string } // another chapter of this manual
  | { kind: "tour" };

export interface HelpChapter {
  key: string;
  icon: IconName;
  /** Card title and one-liner — English keys, translated through t(). */
  title: string;
  blurb: string;
  /** Markdown body, loaded from ./zh-CN/<file>.md */
  body: string;
  /** The "take me there" button above the body. */
  goto?: { label: string; action: HelpAction };
}

// file basename → chapter key. The numeric prefix fixes reading order; the key is what
// `app:help/<key>` links and testids use, so it must stay stable if a file is renamed.
const ORDER: { file: string; key: string; icon: IconName; title: string; blurb: string;
  goto?: { label: string; action: HelpAction } }[] = [
  {
    file: "01-开始",
    key: "start",
    icon: "sparkle",
    title: "Getting started",
    blurb: "What it actually is, how one session goes, and the three rules worth memorizing.",
    goto: { label: "Replay the guided tour", action: { kind: "tour" } },
  },
  {
    file: "02-选模型",
    key: "models",
    icon: "code",
    title: "Choosing a model",
    blurb: "What the suffix after the model name tells you about who pays — and how to make the free one your default.",
    goto: { label: "Open Settings ▸ Models", action: { kind: "settings", tab: "models" } },
  },
  {
    file: "03-省钱",
    key: "cost",
    icon: "refresh",
    title: "Spending less",
    blurb: "Where the tokens actually go, how to read the usage chip, and seven habits that keep the bill down.",
    goto: { label: "Open Settings ▸ Context optimization", action: { kind: "settings", tab: "context" } },
  },
  {
    file: "04-用技能",
    key: "skills",
    icon: "book",
    title: "Using skills",
    blurb: "How a skill gets picked up, why installing thirty of them costs you every turn, and how to choose.",
    goto: { label: "Open Settings ▸ Skills", action: { kind: "settings", tab: "skills" } },
  },
  {
    file: "05-自建技能",
    key: "build-skill",
    icon: "pencil",
    title: "Building your own skill",
    blurb: "When a repeated instruction is worth writing down, and the four ways to create one.",
    goto: { label: "Open Settings ▸ Skills", action: { kind: "settings", tab: "skills" } },
  },
  {
    file: "06-专家与组团",
    key: "experts",
    icon: "diamond",
    title: "Experts and teams",
    blurb: "Reading a prompt is free; a three-person team costs three times as much. When each is worth it.",
    goto: { label: "Open the Expert library", action: { kind: "surface", to: "library" } },
  },
  {
    file: "07-协作代理",
    key: "coworkers",
    icon: "wrench",
    title: "Coworkers",
    blurb: "The nine shipped roles, why none are on by default, and why they can't join a team.",
    goto: { label: "Open Settings ▸ Coworkers", action: { kind: "settings", tab: "personas" } },
  },
  {
    file: "08-连接器与自动化",
    key: "connectors",
    icon: "plug",
    title: "Connectors and automations",
    blurb: "Connect only what you use, and do the arithmetic before you schedule anything.",
    goto: { label: "Open Connectors", action: { kind: "surface", to: "integrations" } },
  },
  {
    file: "09-场景示例",
    key: "examples",
    icon: "table",
    title: "Worked examples",
    blurb: "Four real jobs end to end: a tender review, a failure analysis, a research proposal, a manager's week.",
  },
];

export const HELP_CHAPTERS: HelpChapter[] = ORDER.map((c) => ({
  key: c.key,
  icon: c.icon,
  title: c.title,
  blurb: c.blurb,
  goto: c.goto,
  body: BODIES[`./zh-CN/${c.file}.md`] ?? "",
}));

export function helpChapter(key: string): HelpChapter | undefined {
  return HELP_CHAPTERS.find((c) => c.key === key);
}

// `app:` hrefs written inside the Markdown bodies, e.g. [去设置 ▸ 模型](app:settings/models).
// Returns null for anything unrecognized so a typo renders as inert text rather than
// navigating somewhere surprising.
const SETTINGS_TABS: HelpSettingsTab[] = [
  "appearance", "models", "context", "skills", "voice", "memory", "personas",
];
const SURFACES: HelpSurface[] = ["library", "integrations", "scheduled", "inbox"];

export function parseAppTarget(raw: string): HelpAction | null {
  const spec = raw.startsWith("app:") ? raw.slice("app:".length) : raw;
  if (spec === "tour") return { kind: "tour" };
  const slash = spec.indexOf("/");
  if (slash < 0) return null;
  const head = spec.slice(0, slash);
  const rest = spec.slice(slash + 1);
  if (head === "settings" && (SETTINGS_TABS as string[]).includes(rest)) {
    return { kind: "settings", tab: rest as HelpSettingsTab };
  }
  if (head === "surface" && (SURFACES as string[]).includes(rest)) {
    return { kind: "surface", to: rest as HelpSurface };
  }
  if (head === "help" && helpChapter(rest)) return { kind: "help", chapter: rest };
  return null;
}
