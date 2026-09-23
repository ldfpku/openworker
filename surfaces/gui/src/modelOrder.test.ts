import { describe, expect, it } from "vitest";
import { compareModelIds, sortModelIds } from "./modelOrder";

describe("modelOrder — by id, newest first (owner call 2026-09-23)", () => {
  it("puts the higher version first within a vendor", () => {
    expect(
      sortModelIds([
        "aigw:openai/gpt-5.6-terra",
        "aigw:openai/gpt-6-luna",
        "aigw:openai/gpt-6-sol",
        "aigw:openai/gpt-5.6-sol",
      ]),
    ).toEqual([
      "aigw:openai/gpt-6-sol",
      "aigw:openai/gpt-6-luna",
      "aigw:openai/gpt-5.6-terra",
      "aigw:openai/gpt-5.6-sol",
    ]);
    expect(sortModelIds(["anthropic/claude-opus-5", "anthropic/claude-opus-5-5"])).toEqual([
      "anthropic/claude-opus-5-5",
      "anthropic/claude-opus-5",
    ]);
  });

  it("compares digit runs as numbers, so 5.10 sorts above 5.9", () => {
    expect(sortModelIds(["gpt-5.9", "gpt-5.10", "gpt-5.2"])).toEqual(["gpt-5.10", "gpt-5.9", "gpt-5.2"]);
  });

  it("is otherwise plain string order across vendors, case-insensitive", () => {
    expect(
      sortModelIds([
        "aigw:anthropic/claude-haiku-4-5",
        "aigw:workers-ai/@cf/qwen/qwq-32b",
        "aigw:google-ai-studio/gemini-3.6-flash",
        "aigw:openai/gpt-6-luna",
      ]),
    ).toEqual([
      "aigw:workers-ai/@cf/qwen/qwq-32b",
      "aigw:openai/gpt-6-luna",
      "aigw:google-ai-studio/gemini-3.6-flash",
      "aigw:anthropic/claude-haiku-4-5",
    ]);
    expect(sortModelIds(["minimax:MiniMax-M3", "minimax:MiniMax-M2.5"])).toEqual([
      "minimax:MiniMax-M3",
      "minimax:MiniMax-M2.5",
    ]);
  });

  it("is a total, non-mutating order", () => {
    const input = ["b-1", "a-2", "a-10"];
    const out = sortModelIds(input);
    expect(out).toEqual(["b-1", "a-10", "a-2"]);
    expect(input).toEqual(["b-1", "a-2", "a-10"]);
    expect(compareModelIds("x", "x")).toBe(0);
    expect(compareModelIds("gpt-8", "gpt-08")).not.toBe(0);
  });
});
