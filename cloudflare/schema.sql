CREATE TABLE IF NOT EXISTS calls (
  call_id TEXT PRIMARY KEY,
  direction TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  duration_seconds REAL NOT NULL,
  outcome TEXT NOT NULL,
  summary TEXT,
  error TEXT,
  caller_number TEXT,
  received_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS calls_started_at_desc ON calls (started_at DESC);
