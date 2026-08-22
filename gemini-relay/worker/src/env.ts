/** Worker bindings. Declared once here so the other modules can't drift apart. */
export interface Env {
  /** Roster + session/token store. Key prefixes: `u:` user, `t:` relay token, `s:` pending
   *  login session, `c:` one-time auth code. */
  ROSTER: KVNamespace;
  /** Usage ledger, quota counters, and login audit trail. */
  USAGE_DB: D1Database;

  /** `https://<team-name>.cloudflareaccess.com` — the Access token issuer. */
  ACCESS_TEAM_DOMAIN: string;
  /** Application Audience (AUD) tag of the Access application guarding `/login`. */
  ACCESS_AUD: string;

  /**
   * House default ceilings, applied to anyone whose roster entry does not override them
   * (see quota.ts). Plain vars, not secrets — publishing "you get 1200 requests a day" to
   * the people it applies to is the point. `-1` disables a ceiling, `0` suspends.
   *
   * There is deliberately no `GEMINI_API_KEY` here. Every caller presents their own Google
   * key in `x-goog-api-key` and the relay forwards it untouched, so the relay never holds a
   * credential that could bill anyone.
   */
  QUOTA_RPM: string;
  QUOTA_RPD: string;
  QUOTA_TPD: string;
}
