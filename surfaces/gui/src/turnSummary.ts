// Turn-group summary + timeline glyphs (participation of Transcript.tsx's TurnGroup/StepRow).
// Pure, i18n-free helpers so they're cheap to unit test: summarizeTurn returns typed segments
// (key + optional count) and the caller (TurnGroup) does the t()/join(" · ") — stepIcon and
// formatElapsed likewise just map/format, no strings baked in.

import type { Item } from "./types";
import type { IconName } from "./components/Icon";

type ToolItem = Extract<Item, { kind: "tool" }>;

const EDIT_TOOLS = new Set(["write_file", "replace_in_file", "apply_patch", "apply_unified_diff"]);
const MEMORY_TOOLS = new Set(["remember", "memory_update", "memory_forget"]);
const LOAD_TOOLS_RE = /^load_.+_tools$/;

export interface TurnSummarySegment {
  // Suffix of the `transcript.turn.` i18n key (e.g. "used_tools" → "transcript.turn.used_tools").
  key: string;
  // Absent for count-less segments ("loaded_tools" — presence, not a count).
  count?: number;
}

// `usedCount` is the row-based count TurnGroup already computes (nSteps: tool rows + ask rows
// for declined approvals with no executed call) — NOT tools.length, since a declined ask never
// produced a ToolItem to count here.
export function summarizeTurn(tools: ToolItem[], usedCount: number): TurnSummarySegment[] {
  const segments: TurnSummarySegment[] = [];
  if (usedCount > 0) segments.push({ key: "used_tools", count: usedCount });

  const commands = tools.filter((t) => t.name === "run_shell").length;
  if (commands > 0) segments.push({ key: "ran_commands", count: commands });

  const edited = tools.filter((t) => EDIT_TOOLS.has(t.name)).length;
  if (edited > 0) segments.push({ key: "edited_files", count: edited });

  if (tools.some((t) => LOAD_TOOLS_RE.test(t.name))) segments.push({ key: "loaded_tools" });

  const skills = tools.filter((t) => t.name === "load_skill").length;
  if (skills > 0) segments.push({ key: "used_skills", count: skills });

  const memories = tools.filter((t) => MEMORY_TOOLS.has(t.name)).length;
  if (memories > 0) segments.push({ key: "saved_memories", count: memories });

  return segments;
}

// Timeline row glyph, by tool name. Falls through to a generic wrench for anything unmapped.
export function stepIcon(name: string): IconName {
  switch (name) {
    case "run_shell":
    case "shell_task_output":
    case "shell_task_kill":
      return "terminal";
    case "read_file":
      return "file";
    case "write_file":
    case "replace_in_file":
    case "apply_patch":
    case "apply_unified_diff":
      return "pencil";
    case "grep":
    case "web_search":
      return "search";
    case "web_fetch":
      return "globe";
    case "load_skill":
    case "save_skill":
      return "book";
    case "remember":
    case "memory_update":
    case "memory_forget":
      return "pin";
    case "ask_user":
    case "propose_plan":
    case "send_message":
      return "chat";
    case "explore":
      return "sparkle";
    case "request_directory":
      return "folder";
    default:
      if (LOAD_TOOLS_RE.test(name)) return "plug";
      return "wrench";
  }
}

// <60s → "12s"; otherwise "m:ss" (Composer.tsx's recording-clock format, not shared — that one
// is module-private and always pads to m:ss even under a minute).
export function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
