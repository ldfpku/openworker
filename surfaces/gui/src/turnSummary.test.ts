import { describe, expect, it } from "vitest";
import { summarizeTurn, stepIcon, formatElapsed } from "./turnSummary";
import type { Item } from "./types";

type ToolItem = Extract<Item, { kind: "tool" }>;

function tool(name: string): ToolItem {
  return { kind: "tool", id: name, name, args: {}, status: "ok" };
}

describe("summarizeTurn", () => {
  it("returns nothing for an empty turn", () => {
    expect(summarizeTurn([], 0)).toEqual([]);
  });

  it("uses the row-based usedCount, not tools.length, for the first segment", () => {
    // A declined ask contributes to `usedCount` (§ nSteps) without ever producing a ToolItem.
    expect(summarizeTurn([], 1)).toEqual([{ key: "used_tools", count: 1 }]);
  });

  it("counts each category independently and only emits categories with activity", () => {
    const tools = [tool("run_shell"), tool("write_file"), tool("read_file")];
    expect(summarizeTurn(tools, 3)).toEqual([
      { key: "used_tools", count: 3 },
      { key: "ran_commands", count: 1 },
      { key: "edited_files", count: 1 },
    ]);
  });

  it("counts all four edit-tool names as edited_files", () => {
    const tools = ["write_file", "replace_in_file", "apply_patch", "apply_unified_diff"].map(tool);
    expect(summarizeTurn(tools, 4)).toEqual([
      { key: "used_tools", count: 4 },
      { key: "edited_files", count: 4 },
    ]);
  });

  it("loaded_tools is a presence flag, not a count, matched by /^load_.+_tools$/", () => {
    const tools = [tool("load_browser_tools"), tool("load_email_tools")];
    expect(summarizeTurn(tools, 2)).toEqual([
      { key: "used_tools", count: 2 },
      { key: "loaded_tools" },
    ]);
  });

  it("load_skill counts as used_skills, not loaded_tools", () => {
    const tools = [tool("load_skill")];
    expect(summarizeTurn(tools, 1)).toEqual([
      { key: "used_tools", count: 1 },
      { key: "used_skills", count: 1 },
    ]);
  });

  it("counts the three memory tools as saved_memories", () => {
    const tools = ["remember", "memory_update", "memory_forget"].map(tool);
    expect(summarizeTurn(tools, 3)).toEqual([
      { key: "used_tools", count: 3 },
      { key: "saved_memories", count: 3 },
    ]);
  });

  it("keeps the fixed segment order regardless of input order", () => {
    const tools = [tool("remember"), tool("load_skill"), tool("load_x_tools"), tool("write_file"), tool("run_shell")];
    expect(summarizeTurn(tools, 5).map((s) => s.key)).toEqual([
      "used_tools",
      "ran_commands",
      "edited_files",
      "loaded_tools",
      "used_skills",
      "saved_memories",
    ]);
  });
});

describe("stepIcon", () => {
  it.each([
    ["run_shell", "terminal"],
    ["shell_task_output", "terminal"],
    ["shell_task_kill", "terminal"],
    ["read_file", "file"],
    ["write_file", "pencil"],
    ["replace_in_file", "pencil"],
    ["apply_patch", "pencil"],
    ["apply_unified_diff", "pencil"],
    ["grep", "search"],
    ["web_search", "search"],
    ["web_fetch", "globe"],
    ["load_skill", "book"],
    ["save_skill", "book"],
    ["remember", "pin"],
    ["memory_update", "pin"],
    ["memory_forget", "pin"],
    ["ask_user", "chat"],
    ["propose_plan", "chat"],
    ["send_message", "chat"],
    ["explore", "sparkle"],
    ["request_directory", "folder"],
    ["load_browser_tools", "plug"],
    ["gmail_search_messages", "wrench"],
  ])("%s → %s", (name, expected) => {
    expect(stepIcon(name)).toBe(expected);
  });
});

describe("formatElapsed", () => {
  it("renders under a minute as bare seconds", () => {
    expect(formatElapsed(0)).toBe("0s");
    expect(formatElapsed(45_000)).toBe("45s");
    expect(formatElapsed(59_999)).toBe("59s");
  });

  it("renders a minute or more as m:ss", () => {
    expect(formatElapsed(60_000)).toBe("1:00");
    expect(formatElapsed(125_000)).toBe("2:05");
  });
});
