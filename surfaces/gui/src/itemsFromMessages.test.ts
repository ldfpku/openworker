// The `_display` sidecar on a persisted tool message (privacy-filter hidden
// counts) must surface on the replayed tool item — and only there; the
// agent-visible content string carries no trace.
import { afterEach, describe, expect, it } from "vitest";
import { retryAnchor } from "./components/Transcript";
import i18n from "./i18n";
import { itemsFromMessages } from "./itemsFromMessages";

describe("itemsFromMessages _display sidecar", () => {
  it("attaches hidden counts to the matching tool item", () => {
    const items = itemsFromMessages([
      { role: "user", content: "check my mail" },
      {
        role: "assistant",
        content: "",
        tool_calls: [
          { id: "t1", function: { name: "gmail_search_messages", arguments: "{}" } },
          { id: "t2", function: { name: "gmail_get_message", arguments: "{}" } },
        ],
      },
      {
        role: "tool",
        tool_call_id: "t1",
        content: '{"ok": true, "data": {"messages": []}}',
        _display: { hidden_by_filters: 2, connector: "gmail" },
      },
      { role: "tool", tool_call_id: "t2", content: '{"ok": true}' },
    ] as any);

    const tools = items.filter((i: any) => i.kind === "tool") as any[];
    expect(tools).toHaveLength(2);
    expect(tools[0].hidden).toBe(2);
    expect(tools[1].hidden).toBeUndefined();
    expect(tools[0].preview).not.toContain("hidden"); // content stays clean
  });
});

describe("itemsFromMessages timestamps", () => {
  it("carries the server ts through to user/assistant items; pre-stamp history gets none", () => {
    const items = itemsFromMessages([
      { role: "user", content: "hi", ts: 1752969720 },
      { role: "assistant", content: "hello", ts: 1752969724 },
      { role: "user", content: "old message" }, // saved before the server stamped ts
    ] as any);

    expect(items).toEqual([
      { kind: "user", text: "hi", ts: 1752969720 },
      { kind: "assistant", text: "hello", ts: 1752969724 },
      { kind: "user", text: "old message" },
    ]);
  });
});

describe("itemsFromMessages notices", () => {
  it("replays persisted error/interrupted markers; only errors are retriable", () => {
    const items = itemsFromMessages([
      { role: "user", content: "hi" },
      { role: "assistant", content: "partial ans" },
      { role: "notice", kind: "interrupted", ts: 1752969720 },
      { role: "user", content: "again" },
      { role: "notice", kind: "error", text: "model down", ts: 1752969724 },
    ] as any);

    expect(items).toEqual([
      { kind: "user", text: "hi" },
      { kind: "assistant", text: "partial ans" },
      { kind: "notice", tone: "warn", text: "Interrupted." },
      { kind: "user", text: "again" },
      { kind: "notice", tone: "warn", text: "Error: model down", retriable: true },
    ]);
  });
});

describe("itemsFromMessages model switch", () => {
  it("replays the persisted model_switch marker as an info notice", () => {
    const items = itemsFromMessages([
      { role: "user", content: "hi" },
      { role: "notice", kind: "model_switch", text: "Model switched to Kimi K2.6 · Moonshot" },
    ] as any);
    expect(items[1]).toEqual({
      kind: "notice",
      tone: "info",
      text: "Model switched to Kimi K2.6 · Moonshot",
      bookkeeping: true,
    });
  });
});

describe("itemsFromMessages compaction", () => {
  it("replays the persisted compacted marker as an info notice (the divider)", () => {
    const items = itemsFromMessages([
      { role: "user", content: "hi" },
      { role: "notice", kind: "compacted", text: "Context compacted — earlier turns were summarized" },
    ] as any);
    expect(items[1]).toEqual({
      kind: "notice",
      tone: "info",
      text: "Context compacted — earlier turns were summarized",
    });
  });
});

describe("itemsFromMessages reasoning", () => {
  it("attaches the reasoning sidecar to assistant items; thinking-only messages still render", () => {
    const items = itemsFromMessages([
      { role: "user", content: "hi" },
      { role: "assistant", content: "answer", reasoning: "let me think" },
      { role: "assistant", content: "", reasoning: "stopped mid-thought" },
    ] as any);
    expect(items[1]).toEqual({ kind: "assistant", text: "answer", reasoning: "let me think" });
    expect(items[2]).toEqual({ kind: "assistant", text: "", reasoning: "stopped mid-thought" });
  });
});

describe("itemsFromMessages mcp failure", () => {
  it("replays the persisted mcp_error marker as a collapsed notice WITHOUT retry", () => {
    // Legacy format (no `server` field): the name is recovered from the text and the
    // old plain-text Settings pointer is dropped — the Open Connectors button owns it.
    const items = itemsFromMessages([
      { role: "user", content: "hi" },
      { role: "notice", kind: "mcp_error", text: "MCP server “sales-db” failed to start — see Settings ▸ Connectors" },
    ] as any);
    expect(items[1]).toEqual({
      kind: "notice",
      tone: "warn",
      text: "MCP server “sales-db” didn’t start — its tools are unavailable here",
      server: "sales-db",
      detail: "MCP server “sales-db” failed to start",
    });
  });

  it("keeps an unparseable mcp_error text as a plain warn notice", () => {
    const items = itemsFromMessages([
      { role: "notice", kind: "mcp_error", text: "something opaque went wrong" },
    ] as any);
    expect(items[0]).toEqual({ kind: "notice", tone: "warn", text: "something opaque went wrong" });
  });

  it("renders a project_presence notice as one quiet info line, never an error", () => {
    const items = itemsFromMessages([
      {
        role: "notice",
        kind: "project_presence",
        text: "“notes” already has project memory (3 entries) — bind it by name or start a session there to use it.",
      },
    ] as any);
    expect(items[0]).toEqual({
      kind: "notice",
      tone: "info",
      text: "“notes” already has project memory (3 entries) — bind it by name or start a session there to use it.",
    });
  });
});

describe("itemsFromMessages answer_superseded", () => {
  // Persisted by the server when a durable resume found the answered call overtaken by a later
  // message (manager `_note_superseded_answer`). Without its own arm it fell into the catch-all
  // and rendered as "Error: …" with a Retry button — which the server would ignore: engine
  // `retry()` only acts on an error / turn_aborted tail.
  const superseded = {
    role: "notice",
    kind: "answer_superseded",
    text: "The answer to write_file (allow) came in after the conversation had moved on, so it was not applied: write_file did not run.",
    prompt: "approval",
    resolution: "allow",
    tool: "write_file",
  };

  it("renders as a warning line that names the tool, not as an error", () => {
    const items = itemsFromMessages([superseded] as any);
    expect(items).toEqual([
      {
        kind: "notice",
        tone: "warn",
        text:
          "Your answer to write_file (approved) came in after the conversation had moved on, " +
          "so it was not applied — write_file did not run.",
      },
    ]);
  });

  it("offers no Retry, and does not let one through from an error before it", () => {
    const items = itemsFromMessages([
      { role: "user", content: "hi" },
      { role: "notice", kind: "error", text: "boom" },
      superseded,
    ] as any);
    expect(items[items.length - 1]).not.toHaveProperty("retriable");
    // The server's retry guard (`_tail_is_retriable_error`) only looks through model_switch
    // notices, so a Retry offered here would do nothing.
    expect(retryAnchor(items)).toBe(-1);
  });
});

describe("itemsFromMessages mode switch/notice localization", () => {
  // coworker/permissions.py persists these markers in English forever (old session rows
  // can't be rewritten); the GUI translates them at display time (modeNotice.ts) using the
  // same words the Composer's mode picker already shows for each mode.
  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("renders persisted mode_switch/mode_notice markers unchanged under English (no regression)", () => {
    expect(
      itemsFromMessages([{ role: "notice", kind: "mode_switch", text: "Bypass approvals is on." }] as any)[0],
    ).toEqual({ kind: "notice", tone: "info", text: "Bypass approvals is on.", bookkeeping: true });

    const notice = itemsFromMessages([
      {
        role: "notice",
        kind: "mode_notice",
        title: "Auto-approve is on.",
        text:
          "Auto-approve uses a model to let routine actions through without asking; anything " +
          "it isn't sure about still comes to you. It cuts interruptions but still carries " +
          "some risk i.e. a command it allows still reaches anything you can. These are model " +
          "judgments, and not guarantees.",
      },
    ] as any)[0] as any;
    expect(notice.title).toBe("Auto-approve is on.");
    expect(notice.text).toMatch(/^Auto-approve uses a model/);
  });

  it("localizes a mode_switch marker under zh, for every label MODE_LABELS produces", async () => {
    await i18n.changeLanguage("zh");
    const cases: Array<[string, string]> = [
      ["Discuss is on.", "已开启：讨论"],
      ["Plan is on.", "已开启：计划"],
      ["Ask for approval is on.", "已开启：请求允许"],
      ["Bypass approvals is on.", "已开启：绕过审批"],
      ["Auto-approve is on.", "已开启：自动审批"],
    ];
    for (const [text, expected] of cases) {
      const items = itemsFromMessages([{ role: "notice", kind: "mode_switch", text }] as any);
      expect(items[0], text).toEqual({ kind: "notice", tone: "info", text: expected, bookkeeping: true });
    }
  });

  it("never rewrites a mode_switch text that isn't one of the five known labels", async () => {
    await i18n.changeLanguage("zh");
    const items = itemsFromMessages([
      { role: "notice", kind: "mode_switch", text: "Something else is on." },
    ] as any);
    expect(items[0]).toEqual({
      kind: "notice",
      tone: "info",
      text: "Something else is on.",
      bookkeeping: true,
    });
  });

  it("localizes the once-per-session mode_notice explainer's title and body under zh", async () => {
    await i18n.changeLanguage("zh");
    const items = itemsFromMessages([
      {
        role: "notice",
        kind: "mode_notice",
        title: "Auto-approve is on.",
        text:
          "Auto-approve uses a model to let routine actions through without asking; anything " +
          "it isn't sure about still comes to you. It cuts interruptions but still carries " +
          "some risk i.e. a command it allows still reaches anything you can. These are model " +
          "judgments, and not guarantees.",
      },
    ] as any);
    const notice = items[0] as any;
    expect(notice.title).toBe("已开启：自动审批");
    expect(notice.text).toBe(
      "自动审批会用模型来放行常规操作，无需逐一询问；拿不准的操作仍会交由你处理。这样能减少打断，但仍有风险——被放行的指令依然能触达你能触达的任何东西。这些只是模型的判断，并非保证。",
    );
  });

  it("localizes the reviewer_paused breaker notice under zh, carrying the count through", async () => {
    await i18n.changeLanguage("zh");
    const items = itemsFromMessages([
      {
        role: "notice",
        kind: "reviewer_paused",
        text:
          "Auto-approve is paused for the rest of this turn — the reviewer blocked 5 actions " +
          "in a row, so approvals now come to you.",
      },
    ] as any);
    expect(items[0]).toEqual({
      kind: "notice",
      tone: "info",
      text: "自动审批已为本轮对话暂停——审查器连续拦截了 5 次操作，之后的批准将改为询问你。",
    });
  });

  it("localizes the model_switch marker's scaffold under zh, keeping the label verbatim", async () => {
    await i18n.changeLanguage("zh");
    expect(
      itemsFromMessages([
        { role: "notice", kind: "model_switch", text: "Model switched to Kimi K2.6 · Moonshot" },
      ] as any)[0],
    ).toEqual({
      kind: "notice",
      tone: "info",
      text: "模型已切换为 Kimi K2.6 · Moonshot",
      bookkeeping: true,
    });
    // The no-vision suffix travels with the same marker (engine.py appends it when the new
    // model can't read images already in history).
    expect(
      itemsFromMessages([
        {
          role: "notice",
          kind: "model_switch",
          text: "Model switched to glm-5.2 — earlier images can't be read by this model",
        },
      ] as any)[0],
    ).toEqual({
      kind: "notice",
      tone: "info",
      text: "模型已切换为 glm-5.2——此前的图片该模型无法读取",
      bookkeeping: true,
    });
  });

  it("keeps an unrecognized model_switch text unchanged under zh", async () => {
    await i18n.changeLanguage("zh");
    expect(
      itemsFromMessages([
        { role: "notice", kind: "model_switch", text: "Model swapped for something" },
      ] as any)[0],
    ).toEqual({
      kind: "notice",
      tone: "info",
      text: "Model swapped for something",
      bookkeeping: true,
    });
  });
});

// coworker/engine.py, owner report 2026-09-18: a turn the provider cut short used to end
// as "completed", so the thinking text just stopped and the user read a dead turn as a
// finished one. `turn_aborted` (nothing came back) now replays like a provider failure,
// Retry and all; `turn_truncated` (an answer arrived but was clipped) only warns.
describe("itemsFromMessages cut-off turns", () => {
  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("replays an aborted turn as a retriable warning, one sentence per reason", () => {
    const rows = [
      ["no_finish", /cut off before it finished/],
      ["length", /output length limit/],
      ["empty", /empty response/],
      ["filtered", /blocked this response under its content policy/],
    ] as const;
    for (const [reason, expected] of rows) {
      const item = itemsFromMessages([
        { role: "notice", kind: "turn_aborted", reason, text: "server english" },
      ] as any)[0] as any;
      expect(item, reason).toMatchObject({ kind: "notice", tone: "warn", retriable: true });
      expect(item.text, reason).toMatch(expected);
      // No "Error: " scaffold — the server's sentence is already a whole sentence.
      expect(item.text, reason).not.toMatch(/^Error: /);
    }
  });

  it("replays a truncated answer as a warning that is NOT retriable", () => {
    expect(
      itemsFromMessages([
        { role: "notice", kind: "turn_truncated", reason: "length", text: "server english" },
      ] as any)[0],
    ).toEqual({
      kind: "notice",
      tone: "warn",
      text: "The response may be incomplete: the model hit its output length limit.",
    });
  });

  it("localizes both kinds under zh", async () => {
    await i18n.changeLanguage("zh");
    expect(
      (itemsFromMessages([
        { role: "notice", kind: "turn_aborted", reason: "no_finish", text: "server english" },
      ] as any)[0] as any).text,
    ).toBe("模型输出在完成前被中断（上游未发送结束帧），本轮没有产生任何回答或操作。");
    expect(
      (itemsFromMessages([
        { role: "notice", kind: "turn_truncated", reason: "no_finish", text: "server english" },
      ] as any)[0] as any).text,
    ).toBe("这条回复可能不完整：它在上游发出结束帧之前就被截断了。");
  });

  it("falls back to the server's text when the reason is unknown", async () => {
    await i18n.changeLanguage("zh");
    expect(
      (itemsFromMessages([
        { role: "notice", kind: "turn_aborted", reason: "quota_hold", text: "Held upstream." },
      ] as any)[0] as any).text,
    ).toBe("Held upstream.");
  });

  it("still offers Retry on an aborted turn that is the transcript tail", () => {
    const items = itemsFromMessages([
      { role: "user", content: "write the summary" },
      { role: "assistant", content: "" },
      { role: "notice", kind: "turn_aborted", reason: "no_finish", text: "cut off" },
    ] as any);
    expect(retryAnchor(items)).toBe(items.length - 1);
  });

  it("never offers Retry on a truncated turn — the turn completed", () => {
    const items = itemsFromMessages([
      { role: "user", content: "summarize" },
      { role: "assistant", content: "the first three findings are" },
      { role: "notice", kind: "turn_truncated", reason: "length", text: "may be incomplete" },
    ] as any);
    expect(retryAnchor(items)).toBe(-1);
  });

  it("replays an automatic retry as a quiet info line, with its counter", () => {
    expect(
      itemsFromMessages([
        {
          role: "notice",
          kind: "turn_retry",
          reason: "no_finish",
          attempt: 1,
          max: 2,
          text: "server english",
        },
      ] as any)[0],
    ).toEqual({
      kind: "notice",
      tone: "info",
      text: "The model's response was cut off; retrying (1/2)…",
    });
  });

  it("replays a final abort as thinking-then-notice, with Retry still on the tail", () => {
    // The engine persists the abandoned turn's thinking as an `aborted` assistant message
    // (kept for the transcript, never sent to a provider) so the live view and a reload
    // show the same thing — the four minutes of thinking the user actually watched.
    const items = itemsFromMessages([
      { role: "user", content: "write the summary" },
      { role: "assistant", content: "", reasoning: "Write file to reports/…", aborted: true },
      { role: "notice", kind: "turn_aborted", reason: "no_finish", text: "cut off" },
    ] as any);
    expect(items.map((i) => i.kind)).toEqual(["user", "assistant", "notice"]);
    expect((items[1] as any).reasoning).toBe("Write file to reports/…");
    expect((items[1] as any).text).toBe("");
    expect(retryAnchor(items)).toBe(2);
  });

  it("keeps Retry on the aborted tail even after the retry markers", () => {
    // `retryAnchor` looks THROUGH info notices; the retry markers must not consume the
    // button the way a model-switch marker once did.
    const items = itemsFromMessages([
      { role: "user", content: "write the summary" },
      { role: "notice", kind: "turn_retry", reason: "no_finish", attempt: 1, max: 2, text: "r" },
      { role: "notice", kind: "turn_retry", reason: "no_finish", attempt: 2, max: 2, text: "r" },
      {
        role: "notice",
        kind: "turn_aborted",
        reason: "no_finish",
        retries: 2,
        text: "Cut off. Automatic retry didn't help (2 retries).",
      },
    ] as any);
    expect(retryAnchor(items)).toBe(items.length - 1);
    expect((items[items.length - 1] as any).text).toMatch(/\(2 retries\)\.$/);
  });
});
