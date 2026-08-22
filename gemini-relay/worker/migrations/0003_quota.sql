-- Per-person counting gate (worker/src/quota.ts).
--
-- This could have been derived from `usage` with a GROUP BY, and deliberately is not: the
-- gate runs before every single relayed request, and an aggregate over a table that grows
-- forever gets slower every day. A counter table stays two rows per person per minute, and
-- the nightly cron throws those away after three days.
--
-- `bucket` is the time window, prefixed by kind so both live in one table:
--   m|2026-08-22T15:04   one clock minute, Asia/Shanghai  (gates requests-per-minute)
--   d|2026-08-22         one calendar day, Asia/Shanghai  (gates requests and tokens per day)
-- Asia/Shanghai rather than UTC so "today" is the workday the team actually has; the offset
-- is fixed at +08:00 (China has had no DST since 1991), so no timezone table is involved.
--
-- Named `bucket`, not `window`: SQLite treats WINDOW as a keyword (window functions) and it
-- would need quoting at every use site.
CREATE TABLE quota (
  email    TEXT    NOT NULL,        -- verified Access `email` claim, lowercased
  bucket   TEXT    NOT NULL,        -- see above
  requests INTEGER NOT NULL DEFAULT 0,
  tokens   INTEGER NOT NULL DEFAULT 0,  -- upstream totalTokenCount; only meaningful on d| rows
  updated  TEXT    NOT NULL,        -- ISO 8601 UTC of the last increment; the prune key
  PRIMARY KEY (email, bucket)
);

-- The nightly `DELETE FROM quota WHERE updated < ?` scans by time, not by person.
CREATE INDEX idx_quota_updated ON quota(updated);
