// The backend's default-title sentinel ("New session" — coworker/conversations.py,
// coworker/server/manager.py) has to be localized at display time, but ONLY on an exact
// match: a user's own title must never be run through the catalog just because it happens
// to be English text (or even the same words).
import { afterEach, describe, expect, it } from "vitest";
import i18n from "./i18n";
import { rawSessionTitle, sessionDisplayTitle } from "./sessionTitle";

afterEach(async () => {
  await i18n.changeLanguage("en");
});

describe("sessionDisplayTitle", () => {
  it("shows the localized placeholder for the exact default-title sentinel, under zh", async () => {
    await i18n.changeLanguage("zh");
    expect(sessionDisplayTitle({ title: "New session", session_id: "s1" })).toBe("新会话");
  });

  it("renders the sentinel as plain English under the English locale (no visible change)", () => {
    expect(sessionDisplayTitle({ title: "New session", session_id: "s1" })).toBe("New session");
  });

  it("never translates a user's own title, even English text, even under zh", async () => {
    await i18n.changeLanguage("zh");
    // Not the sentinel — a real title the user typed. Must render verbatim, not run
    // through the catalog (which could coincidentally hold a "New session"-shaped key).
    expect(sessionDisplayTitle({ title: "Draft the launch note", session_id: "s1" })).toBe(
      "Draft the launch note",
    );
  });

  it("does not localize near-misses of the sentinel (case, trailing space, punctuation)", async () => {
    await i18n.changeLanguage("zh");
    expect(sessionDisplayTitle({ title: "new session", session_id: "s1" })).toBe("new session");
    expect(sessionDisplayTitle({ title: "New session ", session_id: "s1" })).toBe("New session ");
    expect(sessionDisplayTitle({ title: "New session!", session_id: "s1" })).toBe("New session!");
  });

  it("falls back to the session id when there is no title, unlocalized", async () => {
    await i18n.changeLanguage("zh");
    expect(sessionDisplayTitle({ session_id: "s-raw-id" })).toBe("s-raw-id");
  });
});

describe("rawSessionTitle", () => {
  it("is never localized — always the stored title or session id, verbatim", async () => {
    await i18n.changeLanguage("zh");
    expect(rawSessionTitle({ title: "New session", session_id: "s1" })).toBe("New session");
    expect(rawSessionTitle({ session_id: "s2" })).toBe("s2");
  });
});
