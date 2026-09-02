// coworker/engine.py's context-compaction outcomes (:712, :718) and its compaction-failed
// ask_user prompt (:684-696) are persisted/sent as literal English — see modeNotice.ts's own
// header comments for why. These tests pin the exact-match behavior: known text translates,
// anything else (including an empty string) passes through unchanged.
import { describe, expect, it } from "vitest";
import {
  compactionHeaderText,
  compactionOptionLabel,
  compactionQuestionText,
  compactionText,
} from "./modeNotice";

describe("compactionText", () => {
  it("translates the summarized outcome", () => {
    expect(compactionText("Context compacted — earlier turns were summarized")).toBe(
      "Context compacted — earlier turns were summarized",
    );
  });

  it("translates the trimmed-fallback outcome", () => {
    expect(compactionText("Context trimmed — oldest turns dropped (summary unavailable)")).toBe(
      "Context trimmed — oldest turns dropped (summary unavailable)",
    );
  });

  it("leaves unrelated text unchanged", () => {
    expect(compactionText("something else entirely")).toBe("something else entirely");
  });

  it("returns an empty string unchanged (caller supplies its own fallback)", () => {
    expect(compactionText("")).toBe("");
  });
});

describe("compactionQuestionText / compactionHeaderText", () => {
  it("translates the exact compaction-failed question", () => {
    const raw =
      "Context compaction failed — the summarizer couldn't condense this session's history. How " +
      "should I proceed?";
    expect(compactionQuestionText(raw)).toBe(raw);
  });

  it("leaves an unrecognized question unchanged", () => {
    expect(compactionQuestionText("What's your favorite color?")).toBe(
      "What's your favorite color?",
    );
  });

  it("translates the exact 'Compaction' header", () => {
    expect(compactionHeaderText("Compaction")).toBe("Compaction");
  });

  it("leaves an unrelated header unchanged", () => {
    expect(compactionHeaderText("Chart style")).toBe("Chart style");
  });
});

describe("compactionOptionLabel", () => {
  it("translates the known 'Retry' option", () => {
    expect(compactionOptionLabel("Retry")).toBe("Retry");
  });

  it("translates the known 'Trim oldest 10%' option", () => {
    expect(compactionOptionLabel("Trim oldest 10%")).toBe("Trim oldest 10%");
  });

  it("does not rewrite text that merely resembles a known option", () => {
    expect(compactionOptionLabel("Retry!")).toBe("Retry!");
  });

  it("leaves unrelated options unchanged", () => {
    expect(compactionOptionLabel("staging")).toBe("staging");
  });
});
