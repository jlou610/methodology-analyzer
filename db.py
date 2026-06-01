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


# ── Methodology specs (CRUD fleshed out in Weekend 2) ────────────────
def list_specs(user_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT id, name, is_active, updated_at FROM methodology_specs "
            "WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()


# ── Analysis sessions (CRUD fleshed out in Weekend 2) ────────────────
def list_sessions(user_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT id, title, outcome, created_at FROM analysis_sessions "
            "WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()


def count_sessions_today(user_id):
    """Used by the 10/user/day rate limit in Weekend 2."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM analysis_sessions "
            "WHERE user_id = ? AND date(created_at) = date('now')",
            (user_id,),
        ).fetchone()
        return row["n"]
