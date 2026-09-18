// coworker/engine.py's context-compaction outcomes (:712, :718) and its compaction-failed
// ask_user prompt (:684-696) are persisted/sent as literal English — see modeNotice.ts's own
// header comments for why. These tests pin the exact-match behavior: known text translates,
// anything else (including an empty string) passes through unchanged.
import { afterEach, describe, expect, it } from "vitest";
import i18n from "./i18n";
import {
  compactionHeaderText,
  compactionOptionLabel,
  compactionQuestionText,
  compactionText,
  turnAbortedText,
  turnRetryText,
  turnTruncatedText,
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

// coworker/engine.py's abnormal turn endings. Unlike everything above these carry a
// structured `reason` next to the English sentence, so the lookup is on the reason — an
// unknown or missing one must fall back to the server's text rather than render nothing.
describe("turnAbortedText / turnTruncatedText", () => {
  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("maps each abort reason to its own English sentence", () => {
    expect(turnAbortedText("no_finish", "raw")).toMatch(/cut off before it finished/);
    expect(turnAbortedText("length", "raw")).toMatch(/output length limit/);
    expect(turnAbortedText("empty", "raw")).toBe("The model returned an empty response.");
    expect(turnAbortedText("filtered", "raw")).toBe(
      "The provider blocked this response under its content policy.",
    );
  });

  it("maps each truncation reason to its own English sentence", () => {
    expect(turnTruncatedText("no_finish", "raw")).toMatch(/^The response may be incomplete/);
    expect(turnTruncatedText("length", "raw")).toMatch(/output length limit/);
  });

  it("localizes both notices under zh", async () => {
    await i18n.changeLanguage("zh");
    expect(turnAbortedText("no_finish", "raw")).toBe(
      "模型输出在完成前被中断（上游未发送结束帧），本轮没有产生任何回答或操作。",
    );
    expect(turnAbortedText("length", "raw")).toBe("模型在给出回答前就触及了输出长度上限。");
    expect(turnAbortedText("empty", "raw")).toBe("模型返回了空回复。");
    expect(turnAbortedText("filtered", "raw")).toBe("这条回复被提供商的内容策略拦截了。");
    expect(turnTruncatedText("no_finish", "raw")).toBe(
      "这条回复可能不完整：它在上游发出结束帧之前就被截断了。",
    );
    expect(turnTruncatedText("length", "raw")).toBe("这条回复可能不完整：模型触及了输出长度上限。");
  });

  it("falls back to the server's English text for a reason it doesn't know", async () => {
    await i18n.changeLanguage("zh");
    expect(turnAbortedText("quota_hold", "The provider held the response.")).toBe(
      "The provider held the response.",
    );
    expect(turnAbortedText(undefined, "Something went wrong.")).toBe("Something went wrong.");
    // `empty` is an abort reason only — the truncation table must not borrow it.
    expect(turnTruncatedText("empty", "Raw server text.")).toBe("Raw server text.");
  });

  it("says how many times it already retried, once and only once", async () => {
    // The server's own English text already carries the sentence, so the fallback branch
    // must NOT add a second copy of it.
    expect(
      turnAbortedText("quota_hold", "Cut off. Automatic retry didn't help (2 retries).", 2),
    ).toBe("Cut off. Automatic retry didn't help (2 retries).");
    expect(turnAbortedText("no_finish", "raw", 2)).toMatch(/\(2 retries\)\.$/);
    expect(turnAbortedText("no_finish", "raw", 0)).not.toMatch(/retries/);
    await i18n.changeLanguage("zh");
    expect(turnAbortedText("no_finish", "raw", 2)).toBe(
      "模型输出在完成前被中断（上游未发送结束帧），本轮没有产生任何回答或操作。自动重试未能解决（重试 2 次）。",
    );
  });
});

describe("turnRetryText", () => {
  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("interpolates the attempt counter into each reason's sentence", () => {
    expect(turnRetryText("no_finish", 1, 2, "raw")).toBe(
      "The model's response was cut off; retrying (1/2)…",
    );
    expect(turnRetryText("empty", 2, 2, "raw")).toBe(
      "The model returned an empty response; retrying (2/2)…",
    );
    expect(turnRetryText("transient", 1, 3, "raw")).toBe(
      "The model call failed; retrying (1/3)…",
    );
  });

  it("localizes under zh", async () => {
    await i18n.changeLanguage("zh");
    expect(turnRetryText("no_finish", 1, 2, "raw")).toBe(
      "模型输出被中断，正在自动重试（第 1/2 次）…",
    );
    expect(turnRetryText("transient", 2, 2, "raw")).toBe(
      "模型调用失败，正在自动重试（第 2/2 次）…",
    );
  });

  it("falls back to the server's text for an unknown reason", async () => {
    await i18n.changeLanguage("zh");
    expect(turnRetryText("weird", 1, 2, "Retrying, hang on.")).toBe("Retrying, hang on.");
  });
});
