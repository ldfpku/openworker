import i18n from "./i18n";

// The backend hands out a fixed placeholder title for any session that hasn't been named yet
// — `_default_title` in coworker/conversations.py and the `list_sessions` fallback in
// coworker/server/manager.py both return the literal string below. It's written into the
// session row at creation time, so it's stuck in old rows exactly as-is; we can't localize it
// by changing the generator without leaving every existing session's title English forever.
// Translate it here instead, at display time, so old and new sessions both render localized.
//
// This must be an EXACT match on the raw `title` field, never a substring/trim check and never
// run through t() unconditionally: a user who typed this same string as their own session title
// (rare, but not impossible — it's literally the sidebar's own "+ New session" wording) would
// otherwise have their own words rewritten under them.
const DEFAULT_TITLE_SENTINEL = "New session";

/** The title exactly as stored (falling back to the session id) — for editing/renaming and for
 *  comparisons against what the user actually typed. Never localized: this is the real data. */
export function rawSessionTitle(s: { title?: string; session_id: string }): string {
  return s.title || s.session_id;
}

/** The title as it should be shown in the GUI: the untitled-session sentinel renders localized,
 *  everything else — including a user's own title that happens to read "New session" — renders
 *  verbatim. Use this for every session-title label; use `rawSessionTitle` for editing. */
export function sessionDisplayTitle(s: { title?: string; session_id: string }): string {
  return s.title === DEFAULT_TITLE_SENTINEL ? i18n.t("sidebar.untitled_session") : rawSessionTitle(s);
}

/** Same sentinel mapping for endpoints that hand back a bare `session_title` string (inbox
 *  items, subscriptions, connector listening rows) instead of a full SessionInfo. `fallback`
 *  is what the call site showed before when the title was empty (usually the session id). */
export function sessionTitleText(title: string | undefined, fallback = ""): string {
  if (title === DEFAULT_TITLE_SENTINEL) return i18n.t("sidebar.untitled_session");
  return title || fallback;
}
