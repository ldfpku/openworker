// A gate answered from WeChat (or timed out) arrives as `prompt_resolved`, and resolving the
// item makes its inline card disappear — App.tsx renders approval/directory/plan/tool cards
// only while `!item.resolved`. So the transcript line built here is the ONLY thing that tells
// the user their gate was answered elsewhere rather than silently vanishing.
//
// The resolutions it has to read are not the canonical ones the card offered: a WeChat reply
// can type its own folder path, and "Approve and run" sends mode="bypass-approvals". Same
// reason `interactions.outcome_text` reads the verdict field server-side.
import { afterEach, describe, expect, it } from "vitest";
import { retryAnchor } from "./components/Transcript";
import i18n from "./i18n";
import { answerSupersededNotice, promptOutcome, promptResolvedNotice } from "./promptResolved";
import type { Item } from "./types";

afterEach(async () => {
  await i18n.changeLanguage("en");
});

describe("promptOutcome", () => {
  it("reads an approval's bare allow/deny", () => {
    expect(promptOutcome("approval", "allow")).toBe("approved");
    expect(promptOutcome("approval", "deny")).toBe("declined");
  });

  it("reads a directory grant whatever path it carries", () => {
    expect(
      promptOutcome("directory", JSON.stringify({ granted: true, path: "/tmp/logs", writable: true })),
    ).toBe("approved");
    expect(promptOutcome("directory", JSON.stringify({ granted: false }))).toBe("declined");
  });

  it("reads a plan approved in any mode, including the app's Approve-and-run", () => {
    expect(promptOutcome("plan", JSON.stringify({ approved: true, mode: "bypass-approvals" }))).toBe(
      "approved",
    );
    expect(promptOutcome("plan", JSON.stringify({ approved: true, mode: "interactive" }))).toBe(
      "approved",
    );
    expect(promptOutcome("plan", JSON.stringify({ approved: false }))).toBe("declined");
  });

  it("reads a tool install", () => {
    expect(promptOutcome("tool", JSON.stringify({ approved: true }))).toBe("approved");
    expect(promptOutcome("tool", JSON.stringify({ approved: false }))).toBe("declined");
  });

  it("quotes an ask_user answer back instead of scoring it", () => {
    expect(promptOutcome("question", "staging")).toBe("staging");
  });

  it("truncates a long free-text answer so the line stays one line", () => {
    const long = "x".repeat(200);
    const out = promptOutcome("question", long);
    expect(out.length).toBe(61);
    expect(out.endsWith("…")).toBe(true);
  });

  it("treats unreadable or missing structure as a decline", () => {
    expect(promptOutcome("directory", "not json at all")).toBe("declined");
    expect(promptOutcome("plan", "")).toBe("declined");
    expect(promptOutcome("question", "   ")).toBe("declined");
  });
});

describe("promptResolvedNotice", () => {
  it("names WeChat and the outcome, in Chinese", async () => {
    await i18n.changeLanguage("zh");
    const note = promptResolvedNotice(
      "directory",
      "weixin",
      JSON.stringify({ granted: true, path: "C:\\logs", writable: false }),
    );
    expect(note).toEqual({ kind: "notice", tone: "info", text: "已在微信处理：同意" });
  });

  it("says a prompt nobody answered was declined, and flags it", () => {
    const note = promptResolvedNotice("approval", "timeout", "deny");
    expect(note?.kind).toBe("notice");
    expect(note && "tone" in note && note.tone).toBe("warn");
    expect(note && "text" in note && note.text).toBe("No answer in time — declined.");
  });

  it("stays silent for surfaces it has no wording for", () => {
    // `via: "app"` is never broadcast in the first place; anything unknown must not invent a
    // line claiming WeChat answered.
    expect(promptResolvedNotice("approval", "app", "allow")).toBeNull();
    expect(promptResolvedNotice("approval", "", "allow")).toBeNull();
    expect(promptResolvedNotice("approval", "slack", "allow")).toBeNull();
  });
});

// The server's `answer_superseded` (manager `_note_superseded_answer`): an Inbox answer that came
// in after the conversation had moved past its prompt, so the durable resume ran nothing for it.
// Before this line existed that was total silence — the Inbox said "approved" and nothing ran.
describe("answerSupersededNotice", () => {
  it("names the tool that did not run and the answer that was not applied", () => {
    expect(answerSupersededNotice("approval", "allow", "write_file")).toEqual({
      kind: "notice",
      tone: "warn",
      retryTransparent: true,
      text:
        "Your answer to write_file (approved) came in after the conversation had moved on, " +
        "so it was not applied — write_file did not run.",
    });
  });

  it("says it in Chinese", async () => {
    await i18n.changeLanguage("zh");
    expect(answerSupersededNotice("approval", "allow", "write_file")).toEqual({
      kind: "notice",
      tone: "warn",
      retryTransparent: true,
      text: "你对 write_file 的答复（同意）到达时，对话已经往下进行了，这条答复没有生效，write_file 没有运行。",
    });
    expect(answerSupersededNotice("question", "staging")).toEqual({
      kind: "notice",
      tone: "warn",
      retryTransparent: true,
      text: "有一条答复（staging）到达时，对话已经往下进行了，这条答复没有生效。",
    });
  });

  it("falls back to the generic line without a tool name", () => {
    const note = answerSupersededNotice("directory", JSON.stringify({ granted: true, path: "/tmp" }));
    expect(note).toEqual({
      kind: "notice",
      tone: "warn",
      retryTransparent: true,
      text: "An answer (approved) came in after the conversation had moved on, so it was not applied.",
    });
  });

  it("keeps the Retry of a live error it lands after", () => {
    // The live view (App.tsx): the resumed turn's `error` event, then the server's
    // `answer_superseded` event, which it sends only after that resume is done.
    const items: Item[] = [
      { kind: "user", text: "never mind, do something else" },
      { kind: "notice", tone: "warn", text: "Error: boom", retriable: true },
      answerSupersededNotice("approval", "allow", "write_file"),
    ];
    expect(retryAnchor(items)).toBe(1);
  });
});
