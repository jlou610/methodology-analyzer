-- methodology-analyzer schema (multi-tenant)
-- Every user-owned row carries user_id. All feature queries are scoped by it.
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT DEFAULT (datetime('now'))
);

-- A user's methodology spec (the JSON blob defined in §schema). One user may keep
-- several; is_active marks the one the analyzer uses by default.
CREATE TABLE IF NOT EXISTS methodology_specs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    spec_json  TEXT NOT NULL,
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- One analyzer run: per-session input -> Claude output -> later, recorded outcome.
-- (Output/outcome columns are populated in the Weekend 2 analyzer build.)
CREATE TABLE IF NOT EXISTS analysis_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    spec_id       INTEGER REFERENCES methodology_specs(id) ON DELETE SET NULL,
    title         TEXT,
    input_json    TEXT NOT NULL,
    output_text   TEXT,
    output_json   TEXT,
    outcome       TEXT CHECK(outcome IN ('correct','incorrect','partial','no-trade')),
    what_happened TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_specs_user    ON methodology_specs(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON analysis_sessions(user_id);
-- Supports the 10/user/day rate limit (Weekend 2): count today's rows per user.
CREATE INDEX IF NOT EXISTS idx_sessions_user_created ON analysis_sessions(user_id, created_at);
