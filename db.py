"""
Persistent storage for the authenticated product: accounts, sessions, and
every protocol a signed-in user has ever verified.

SQLite via the standard library, one file (verilab.db, gitignored, never
committed since it holds real user data). Deliberately not an in-memory
store: it has to survive a server restart for "every verification run is
saved" to actually be true.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "verilab.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    encrypted_api_key TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS protocols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    protocol_name TEXT NOT NULL,
    source_text TEXT NOT NULL,
    status TEXT NOT NULL,
    error_count INTEGER NOT NULL,
    warning_count INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_protocols_user ON protocols(user_id);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(email: str, password_hash: str, display_name: str, created_at: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, display_name, created_at) VALUES (?, ?, ?, ?)",
            (email, password_hash, display_name, created_at),
        )
        return cur.lastrowid


def get_user_by_email(email: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def update_display_name(user_id: int, display_name: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id))


def set_api_key(user_id: int, encrypted_api_key: str | None):
    with get_conn() as conn:
        conn.execute("UPDATE users SET encrypted_api_key = ? WHERE id = ?", (encrypted_api_key, user_id))


def delete_user(user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM protocols WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(token: str, user_id: int, created_at: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, created_at),
        )


def get_session(token: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()


def delete_session(token: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

def save_protocol(user_id: int, protocol_name: str, source_text: str, status: str,
                   error_count: int, warning_count: int, result: dict, created_at: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO protocols
               (user_id, protocol_name, source_text, status, error_count, warning_count, result_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, protocol_name, source_text, status, error_count, warning_count,
             json.dumps(result), created_at),
        )
        return cur.lastrowid


def list_protocols(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, protocol_name, source_text, status, error_count, warning_count, created_at "
            "FROM protocols WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()


def get_protocol(protocol_id: int, user_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM protocols WHERE id = ? AND user_id = ?", (protocol_id, user_id)
        ).fetchone()


def user_stats(user_id: int) -> dict:
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM protocols WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        issues = conn.execute(
            "SELECT COALESCE(SUM(error_count + warning_count), 0) AS c FROM protocols WHERE user_id = ?",
            (user_id,),
        ).fetchone()["c"]
        clean = conn.execute(
            "SELECT COUNT(*) AS c FROM protocols WHERE user_id = ? AND status = 'CLEARED'", (user_id,)
        ).fetchone()["c"]
    clean_rate = round((clean / total) * 100) if total else 0
    return {
        "protocols_verified": total,
        "issues_caught": issues,
        "clean_pass_rate": clean_rate,
    }
