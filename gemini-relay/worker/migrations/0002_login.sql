-- v3: identity moves from "sha256(Gemini API key) -> email" to a Cloudflare Access
-- One-time PIN login (worker/src/auth.ts).
--
-- Usage rows now carry the person, not just their address, so a per-department report is a
-- GROUP BY rather than a join against a roster export that may have drifted since. Both
-- columns are denormalized snapshots taken at request time on purpose: if someone changes
-- department, past usage keeps the department it was actually incurred under.
ALTER TABLE usage ADD COLUMN name TEXT DEFAULT '';
ALTER TABLE usage ADD COLUMN dept TEXT DEFAULT '';

-- `usage.key_hash` keeps its name and its 12-hex-char shape, but its meaning changed with
-- this migration: it used to be sha256(Gemini API key)[:12] and is now
-- sha256(relay token)[:12]. Rows written before this migration are the old kind. It stays a
-- "which credential was this" discriminator either way, and still stores no credential.

-- Login audit trail. Kept apart from `usage` because it is security evidence rather than
-- billing data: different questions, different retention, and it must survive even when a
-- login never produces a single relayed request.
CREATE TABLE auth_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,           -- ISO 8601 UTC, new Date().toISOString()
  email TEXT NOT NULL,        -- verified Access `email` claim, lowercased
  event TEXT NOT NULL,        -- login-ok|login-denied|token-issued|token-denied|logout
  detail TEXT DEFAULT '',     -- 'not in roster', 'pkce mismatch', ...
  country TEXT DEFAULT ''     -- country Access saw the login from
);
CREATE INDEX idx_auth_events_ts ON auth_events(ts);
CREATE INDEX idx_auth_events_email_ts ON auth_events(email, ts);
