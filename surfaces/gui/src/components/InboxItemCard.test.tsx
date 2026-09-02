import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { InboxItemCard } from "./InboxItemCard";
import type { InboxItem } from "../api";
import i18n from "../i18n";

// The ask_user schema now only ever advertises the grouped `questions` form (Task C, OPE-51
// follow-up), so a lone question arrives from the model as a ONE-item `questions` array —
// same as before, just always wrapped. A singleton group must render and resolve exactly like
// the legacy singular form: no stepper chrome, no "1 of 1", plain-string resolution. The
// stepper is reserved for 2+ questions (server parity: coworker/tools/ask.py's
// question_item_fields already surfaces a grouped call's first question as title/options).

afterEach(cleanup);

const base = (extra: Partial<InboxItem>): InboxItem => ({
  id: "i1",
  session_id: "s1",
  kind: "question",
  title: "Env?",
  body: "",
  state: "pending",
  resolution: null,
  inbox: "default",
  created_at: "",
  resolved_at: null,
  ...extra,
});

describe("InboxItemCard — singleton `questions` group renders as a plain question card", () => {
  it("shows no stepper chrome and resolves with the plain option label", () => {
    const onResolve = vi.fn();
    const item = base({
      title: "Env?",
      options: ["staging", "prod"],
      allow_text: false,
      questions: [{ question: "Env?", options: ["staging", "prod"], allow_text: false }],
    });
    render(<InboxItemCard item={item} onResolve={onResolve} />);

    // No stepper testid, no "1 of 1" step indicator, no back arrow.
    expect(screen.queryByTestId("question-stepper")).toBeNull();
    expect(screen.queryByText(/1 of 1/)).toBeNull();
    expect(screen.queryByLabelText("Previous question")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "staging" }));
    // Plain answer, not a JSON answers-map — identical to the pre-existing singular form.
    expect(onResolve).toHaveBeenCalledWith("i1", "staging");
  });

  it("renders identically whether the item came from the singular form or a one-item group", () => {
    const singular = base({ title: "Env?", options: ["staging", "prod"] });
    const { container: c1 } = render(<InboxItemCard item={singular} onResolve={vi.fn()} />);
    const singularHtml = c1.innerHTML;
    cleanup();

    const grouped = base({
      title: "Env?",
      options: ["staging", "prod"],
      questions: [{ question: "Env?", options: ["staging", "prod"] }],
    });
    const { container: c2 } = render(<InboxItemCard item={grouped} onResolve={vi.fn()} />);
    expect(c2.innerHTML).toBe(singularHtml);
  });
});

describe("InboxItemCard — compaction-failed question (coworker/engine.py, live ask_user)", () => {
  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("shows the Chinese question/header/options but resolves with the raw English option value", async () => {
    await i18n.changeLanguage("zh");
    const onResolve = vi.fn();
    const item = base({
      title:
        "Context compaction failed — the summarizer couldn't condense this session's history. " +
        "How should I proceed?",
      header: "Compaction",
      options: ["Retry", "Trim oldest 10%"],
      allow_text: false,
    });
    render(<InboxItemCard item={item} onResolve={onResolve} />);

    expect(screen.getByText("上下文压缩")).toBeTruthy();
    expect(
      screen.getByText("上下文压缩失败——摘要器无法压缩本会话的历史。要怎么继续？"),
    ).toBeTruthy();
    const retryButton = screen.getByRole("button", { name: "重试" });
    expect(retryButton).toBeTruthy();

    fireEvent.click(retryButton);
    // The displayed label is translated; the value sent back to the engine (which compares it
    // literally, coworker/engine.py:701) must stay the raw English string.
    expect(onResolve).toHaveBeenCalledWith("i1", "Retry");
  });
});

describe("InboxItemCard — 2+ questions still get the stepper", () => {
  it("keeps the stepper chrome once there is more than one question", () => {
    const item = base({
      title: "Chart style?",
      header: "Chart",
      options: ["Bar", "Line"],
      questions: [
        { question: "Chart style?", header: "Chart", options: ["Bar", "Line"] },
        { question: "Which distribution?", header: "Distribution" },
      ],
    });
    render(<InboxItemCard item={item} onResolve={vi.fn()} />);
    expect(screen.getByTestId("question-stepper")).toBeTruthy();
    expect(screen.getByText(/1 of 2/)).toBeTruthy();
  });
});
