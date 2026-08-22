CREATE TABLE usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,               -- ISO 8601 UTC, new Date().toISOString()
  email TEXT NOT NULL,            -- roster resolution; "(unregistered)"/"(no-key)" for rejected requests
  model TEXT DEFAULT '',          -- extracted from /models/{model}:{method}
  kind TEXT NOT NULL,             -- generate|stream|embed|count|models|files|other
  status INTEGER NOT NULL,        -- HTTP status returned to the client
  key_hash TEXT DEFAULT '',       -- sha256 first 12 hex chars
  model_version TEXT DEFAULT '',  -- echoed modelVersion from the response
  response_id TEXT DEFAULT '',    -- echoed responseId from the response
  prompt_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,   -- candidatesTokenCount
  total_tokens INTEGER DEFAULT 0,
  cached_tokens INTEGER DEFAULT 0,   -- cachedContentTokenCount
  thoughts_tokens INTEGER DEFAULT 0,
  tool_prompt_tokens INTEGER DEFAULT 0,  -- toolUsePromptTokenCount
  latency_ms INTEGER DEFAULT 0,   -- time to upstream response headers
  duration_ms INTEGER DEFAULT 0,  -- total time until the record-side stream is fully consumed
  error TEXT DEFAULT ''           -- ''|no-key|unregistered|parse-fail etc.
);
CREATE INDEX idx_usage_email_ts ON usage(email, ts);
CREATE INDEX idx_usage_ts ON usage(ts);
