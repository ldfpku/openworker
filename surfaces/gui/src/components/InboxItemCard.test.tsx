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

describe("InboxItemCard — parked directory/plan prompts wear translated dress", () => {
  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("names the kind and the fixed server title in Chinese", async () => {
    await i18n.changeLanguage("zh");
    render(
      <InboxItemCard
        item={base({ kind: "directory", title: "Grant access to a folder?", body: "for the logs" })}
        onResolve={vi.fn()}
      />,
    );
    // Both used to render their raw English: the chip looked up the bare word "directory"
    // (no such key) and the title had no key at all.
    expect(screen.getByText("文件夹")).toBeTruthy();
    expect(screen.getByText("授权访问某个文件夹？")).toBeTruthy();
    expect(screen.queryByText("Grant access to a folder?")).toBeNull();
  });

  it("leaves the OTHER plan-kind gates (team, work items) on their own titles", async () => {
    await i18n.changeLanguage("zh");
    render(
      <InboxItemCard item={base({ kind: "plan", title: "Create this team?" })} onResolve={vi.fn()} />,
    );
    expect(screen.getByText("计划")).toBeTruthy();
    expect(screen.getByText("Create this team?")).toBeTruthy();
  });
});

describe("InboxItemCard — 开工前核对 (pre-flight) card", () => {
  const preflightItem = () =>
    base({
      title: "成果主要给谁看？",
      header: "给谁看",
      data: { preflight: true },
      questions: [
        { question: "成果主要给谁看？", header: "给谁看", options: [{ label: "生产部长", recommended: true }] },
        { question: "依据哪些资料来做？", header: "依据在哪", multi: true, options: ["检验记录, 机加", "处理单"] },
      ],
    });

  it("wears the pre-flight title and resolves with the skip sentinel", async () => {
    await i18n.changeLanguage("zh");
    const onResolve = vi.fn();
    render(<InboxItemCard item={preflightItem()} onResolve={onResolve} />);
    expect(screen.getByTestId("preflight-title").textContent).toBe("开工前核对");
    fireEvent.click(screen.getByTestId("preflight-skip"));
    expect(onResolve).toHaveBeenCalledWith("i1", "__preflight_skip__");
  });

  it("shows no title or skip button on an ordinary question", () => {
    const item = preflightItem();
    delete item.data;
    render(<InboxItemCard item={item} onResolve={vi.fn()} />);
    expect(screen.queryByTestId("preflight-title")).toBeNull();
    expect(screen.queryByTestId("preflight-skip")).toBeNull();
  });

  it("keeps a comma inside a multi-select label by resolving with a JSON array", () => {
    const onResolve = vi.fn();
    render(<InboxItemCard item={preflightItem()} onResolve={onResolve} />);
    fireEvent.click(screen.getByText("生产部长")); // step 1 → advances to the multi step
    fireEvent.click(screen.getByText("检验记录, 机加"));
    fireEvent.click(screen.getByText("处理单"));
    fireEvent.click(screen.getByText(/\(2\)/));
    expect(onResolve).toHaveBeenCalledTimes(1);
    const resolution = JSON.parse(onResolve.mock.calls[0][1]);
    expect(resolution).toEqual({ 给谁看: "生产部长", 依据在哪: ["检验记录, 机加", "处理单"] });
  });

  it("resolves a lone multi-select question with the array JSON-encoded", () => {
    const onResolve = vi.fn();
    const item = base({
      title: "Sources?",
      multi: true,
      options: ["a, b", "c"],
      questions: [{ question: "Sources?", multi: true, options: ["a, b", "c"] }],
    });
    render(<InboxItemCard item={item} onResolve={onResolve} />);
    fireEvent.click(screen.getByText("a, b"));
    fireEvent.click(screen.getByText(/\(1\)/));
    expect(onResolve).toHaveBeenCalledWith("i1", JSON.stringify(["a, b"]));
  });
});
