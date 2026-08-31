import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { HelpView } from "./HelpView";
import { HELP_CHAPTERS, parseAppTarget } from "../help";
import { isFreeModel } from "../providers/logos";

afterEach(cleanup);

// The in-app manual. Three things must keep working: the overview is navigation (cards open
// chapters), a chapter's "take me there" button reports the right action, and every `app:`
// link written inside a body resolves — a typo'd chapter link would render as a dead chip
// with no other symptom, so the last one is checked against the real Markdown files.
describe("HelpView", () => {
  it("opens on the card overview and every chapter has a card", () => {
    render(<HelpView onNavigate={vi.fn()} />);
    expect(screen.getByTestId("help-overview")).toBeTruthy();
    for (const c of HELP_CHAPTERS) expect(screen.getByTestId(`help-card-${c.key}`)).toBeTruthy();
  });

  it("clicking a card opens that chapter", () => {
    render(<HelpView onNavigate={vi.fn()} />);
    fireEvent.click(screen.getByTestId("help-card-cost"));
    expect(screen.getByTestId("help-chapter-cost")).toBeTruthy();
    expect(screen.queryByTestId("help-overview")).toBeNull();
  });

  it("deep-links straight to a chapter", () => {
    render(<HelpView initialChapter="models" onNavigate={vi.fn()} />);
    expect(screen.getByTestId("help-chapter-models")).toBeTruthy();
  });

  it("the chapter's goto button reports its action to the host", () => {
    const onNavigate = vi.fn();
    render(<HelpView initialChapter="models" onNavigate={onNavigate} />);
    fireEvent.click(screen.getByTestId("help-goto"));
    expect(onNavigate).toHaveBeenCalledWith({ kind: "settings", tab: "models" });
  });

  it("the sub-nav goes back to the overview", () => {
    render(<HelpView initialChapter="cost" onNavigate={vi.fn()} />);
    fireEvent.click(screen.getByTestId("help-nav-overview"));
    expect(screen.getByTestId("help-overview")).toBeTruthy();
  });

  it("every app: link in every chapter body resolves to a real target", () => {
    const bad: string[] = [];
    for (const c of HELP_CHAPTERS) {
      for (const m of c.body.matchAll(/\]\(app:([^)]+)\)/g)) {
        if (!parseAppTarget(m[1])) bad.push(`${c.key}: app:${m[1]}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("every chapter body actually loaded", () => {
    for (const c of HELP_CHAPTERS) expect(c.body.length).toBeGreaterThan(200);
  });
});

describe("parseAppTarget", () => {
  it("parses the three link shapes", () => {
    expect(parseAppTarget("app:settings/context")).toEqual({ kind: "settings", tab: "context" });
    expect(parseAppTarget("app:surface/library")).toEqual({ kind: "surface", to: "library" });
    expect(parseAppTarget("app:tour")).toEqual({ kind: "tour" });
    expect(parseAppTarget("app:help/cost")).toEqual({ kind: "help", chapter: "cost" });
  });

  it("returns null rather than guessing at anything unrecognized", () => {
    expect(parseAppTarget("app:settings/nope")).toBeNull();
    expect(parseAppTarget("app:surface/session")).toBeNull();
    expect(parseAppTarget("app:help/no-such-chapter")).toBeNull();
    expect(parseAppTarget("app:")).toBeNull();
    expect(parseAppTarget("https://example.com")).toBeNull();
  });
});

// The badge is a claim about who pays, so it must stay pinned to the two routes that
// really cost nothing per token.
describe("isFreeModel", () => {
  it("tags the NVIDIA relay and local Ollama, nothing else", () => {
    expect(isFreeModel("nvidia:moonshotai/kimi-k3")).toBe(true);
    expect(isFreeModel("ollama:qwen3-coder:30b")).toBe(true);
    expect(isFreeModel("anthropic:claude-sonnet-5")).toBe(false);
    expect(isFreeModel("aigw:openai/gpt-5.6")).toBe(false);
    expect(isFreeModel("gpt-5.6")).toBe(false);
  });
});
