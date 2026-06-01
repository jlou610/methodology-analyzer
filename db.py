"""SQLite data layer for methodology-analyzer.

Multi-tenant from the start: every feature row carries user_id and every query
here is scoped by it. The DB file path comes from $DB_PATH (set to the Render
persistent-disk mount in production); defaults to ./data/app.db for local dev.
"""
import os
import sqlite3

DB_PATH = os.environ.get(
    "DB_PATH", os.path.join(os.path.dirname(__file__), "data", "app.db")
)
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist. Safe to call on every boot."""
    with get_db() as conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        _migrate(conn)


def _migrate(conn):
    """Idempotent migrations for DBs created before a schema change."""
    # Widen the analysis_sessions.outcome CHECK to include 'no-trade'.
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='analysis_sessions'"
    ).fetchone()
    if row and "'no-trade'" not in row[0]:
        conn.executescript("""
            PRAGMA foreign_keys=OFF;
            BEGIN;
            ALTER TABLE analysis_sessions RENAME TO _analysis_sessions_old;
            CREATE TABLE analysis_sessions (
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
            INSERT INTO analysis_sessions
                SELECT id, user_id, spec_id, title, input_json, output_text,
                       output_json, outcome, what_happened, created_at
                FROM _analysis_sessions_old;
            DROP TABLE _analysis_sessions_old;
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON analysis_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_user_created ON analysis_sessions(user_id, created_at);
            COMMIT;
            PRAGMA foreign_keys=ON;
        """)


# ── Users ────────────────────────────────────────────────────────────
def create_user(email, password_hash):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email.strip().lower(), password_hash),
        )
        return cur.lastrowid


def get_user_by_email(email):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()


def get_user_by_id(user_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


# ── Methodology specs ────────────────────────────────────────────────
# spec_json holds the full spec object (see schema doc). Every query is
# scoped by user_id, so a user can only ever touch their own specs.
def list_specs(user_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT id, name, is_active, updated_at FROM methodology_specs "
            "WHERE user_id = ? ORDER BY is_active DESC, updated_at DESC",
            (user_id,),
        ).fetchall()


def get_spec(user_id, spec_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM methodology_specs WHERE id = ? AND user_id = ?",
            (spec_id, user_id),
        ).fetchone()


def get_active_spec(user_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM methodology_specs WHERE user_id = ? AND is_active = 1 "
            "ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()


def create_spec(user_id, name, spec_json, make_active=True):
    with get_db() as conn:
        if make_active:
            conn.execute(
                "UPDATE methodology_specs SET is_active = 0 WHERE user_id = ?",
                (user_id,),
            )
        cur = conn.execute(
            "INSERT INTO methodology_specs (user_id, name, spec_json, is_active) "
            "VALUES (?, ?, ?, ?)",
            (user_id, name, spec_json, 1 if make_active else 0),
        )
        return cur.lastrowid


def update_spec(user_id, spec_id, name, spec_json):
    """Edit an existing spec. Returns True if a row owned by the user changed."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE methodology_specs SET name = ?, spec_json = ?, "
            "updated_at = datetime('now') WHERE id = ? AND user_id = ?",
            (name, spec_json, spec_id, user_id),
        )
        return cur.rowcount > 0


def set_active_spec(user_id, spec_id):
    with get_db() as conn:
        owned = conn.execute(
            "SELECT 1 FROM methodology_specs WHERE id = ? AND user_id = ?",
            (spec_id, user_id),
        ).fetchone()
        if not owned:
            return False
        conn.execute(
            "UPDATE methodology_specs SET is_active = 0 WHERE user_id = ?",
            (user_id,),
        )
        conn.execute(
            "UPDATE methodology_specs SET is_active = 1 WHERE id = ? AND user_id = ?",
            (spec_id, user_id),
        )
        return True


def delete_spec(user_id, spec_id):
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM methodology_specs WHERE id = ? AND user_id = ?",
            (spec_id, user_id),
        )
        return cur.rowcount > 0


# ── Analysis sessions ────────────────────────────────────────────────
def list_sessions(user_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT id, title, outcome, created_at FROM analysis_sessions "
            "WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()


def get_analysis_session(user_id, session_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM analysis_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()


def create_analysis_session(user_id, spec_id, title, input_json, output_text, output_json):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO analysis_sessions (user_id, spec_id, title, input_json, "
            "output_text, output_json) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, spec_id, title, input_json, output_text, output_json),
        )
        return cur.lastrowid


def update_outcome(user_id, session_id, outcome, what_happened):
    """Update the outcome + notes on an existing analysis (editable, idempotent).
    Scoped to the owner. Returns True if a row changed."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE analysis_sessions SET outcome = ?, what_happened = ? "
            "WHERE id = ? AND user_id = ?",
            (outcome or None, what_happened, session_id, user_id),
        )
        return cur.rowcount > 0


def count_sessions_today(user_id):
    """Used by the 10/user/day rate limit in Weekend 2."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM analysis_sessions "
            "WHERE user_id = ? AND date(created_at) = date('now')",
            (user_id,),
        ).fetchone()
        return row["n"]
