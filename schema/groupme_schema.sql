PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS groups (
  id TEXT PRIMARY KEY,
  name TEXT
);

CREATE TABLE IF NOT EXISTS members (
  user_id TEXT PRIMARY KEY,
  nickname TEXT,
  image_url TEXT
);

CREATE TABLE IF NOT EXISTS group_members (
  group_id TEXT,
  user_id TEXT,
  role TEXT,
  PRIMARY KEY (group_id, user_id),
  FOREIGN KEY (group_id) REFERENCES groups(id),
  FOREIGN KEY (user_id) REFERENCES members(user_id)
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  group_id TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  user_id TEXT,
  name TEXT,
  text TEXT,
  source_guid TEXT,
  system BOOLEAN DEFAULT 0,
  FOREIGN KEY (group_id) REFERENCES groups(id),
  FOREIGN KEY (user_id) REFERENCES members(user_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_group_ts ON messages(group_id, created_at);

CREATE TABLE IF NOT EXISTS likes (
  message_id TEXT,
  user_id TEXT,
  PRIMARY KEY (message_id, user_id),
  FOREIGN KEY (message_id) REFERENCES messages(id),
  FOREIGN KEY (user_id) REFERENCES members(user_id)
);

CREATE TABLE IF NOT EXISTS reactions (
  message_id TEXT NOT NULL,
  type TEXT,
  code TEXT,
  user_id TEXT NOT NULL,
  PRIMARY KEY (message_id, code, user_id),
  FOREIGN KEY (message_id) REFERENCES messages(id),
  FOREIGN KEY (user_id) REFERENCES members(user_id)
);

CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL,
  type TEXT NOT NULL,
  url TEXT,
  lat REAL, lon REAL,
  name TEXT,
  data TEXT,
  FOREIGN KEY (message_id) REFERENCES messages(id)
);

CREATE TABLE IF NOT EXISTS ingestion_progress (
  group_id TEXT PRIMARY KEY,
  before_id TEXT,
  ingested_count INTEGER DEFAULT 0
);
