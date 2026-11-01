import { describe, expect, it } from "vitest";
// Source-pinned like App.reconnect.test.ts / topbarDrag.test.ts: these are about WHICH
// state transitions fire on send and on a rejection, which jsdom rendering can't
// distinguish from a view that silently lies about being idle.
import APP from "./App.tsx?raw";

// Owner report: while a task was still running the composer looked enabled, the user could
// type and send, and the server rejected it with "already running a turn". The GUI's
// `running` state had drifted from the server's. These pin the client half of the fix.
describe("the composer's running state never lies after a send or a rejection", () => {
  it("a plain user message optimistically marks the session running", () => {
    // send() must setRunning(true) right after handing the message to userMessage(), the
    // same optimistic move retry() makes — so the composer locks immediately instead of
    // staying idle in the window before the server's turn_start (or, for a message the
    // server rejects outright, forever).
    expect(APP).toMatch(
      /sessionRef\.current\?\.userMessage\(text, attachments, model, skill, opts\?\.preflight\);[\s\S]*?setRunning\(true\);/,
    );
    // It also remembers the sent text so a busy rejection can hand it back.
    expect(APP).toMatch(/lastSentRef\.current = \{ text, attachments \};/);
  });

  it("a busy rejection re-asserts running and restores the typed draft", () => {
    // input_rejected with reason "busy": the session was already running a turn the GUI was
    // never told about (a durable resume, a scheduled run). Lock the composer again and
    // give the text back rather than leaving it idle for a resend into another rejection.
    expect(APP).toMatch(
      /if \(d\.reason === "busy"\) \{[\s\S]*?setRunning\(true\);[\s\S]*?prefillComposer\(last\.text, last\.attachments\);/,
    );
  });

  it("a non-busy validation rejection releases the optimistic running", () => {
    // Bad JSON / rate-limit / a bad skill never claimed a turn, so no turn_done will arrive
    // to clear the optimistic running set on send — the else branch must setRunning(false).
    expect(APP).toMatch(
      /if \(d\.reason === "busy"\) \{[\s\S]*?\} else \{[\s\S]*?setRunning\(false\);[\s\S]*?\}/,
    );
  });

  it("a pending question routes EVERY send to the answer, never to userMessage", () => {
    // The question gate keeps the composer unlocked; before the fix a send carrying an
    // attachment or /skill fell through to userMessage() and the server rejected it. Now the
    // branch drops attachments/skill with a notice and answers with the text.
    expect(APP).toMatch(
      /if \(!unattended && pendingQuestion\?\.kind === "question"\) \{[\s\S]*?attachments\?\.length \|\| skill[\s\S]*?app\.notice\.question_text_only[\s\S]*?setComposerAnswer\(/,
    );
    // The question branch (which always returns) sits before the userMessage() fall-through.
    const qIdx = APP.indexOf('pendingQuestion?.kind === "question") {');
    const umIdx = APP.indexOf("sessionRef.current?.userMessage(text, attachments, model");
    expect(qIdx).toBeGreaterThan(-1);
    expect(umIdx).toBeGreaterThan(qIdx);
  });
});
