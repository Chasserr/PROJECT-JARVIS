"""SQLite schema and connection helpers.

Each operation opens a short-lived connection. That is slower than a pool but
keeps asyncio tasks from sharing a connection across threads, which SQLite
explicitly forbids unless every access is serialized.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL DEFAULT 'fact',
    content         BLOB NOT NULL,
    tags            TEXT NOT NULL DEFAULT '[]',
    source          TEXT NOT NULL DEFAULT 'user',
    embedding       BLOB,
    embedding_model TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    deleted_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_memories_live ON memories(deleted_at, updated_at DESC);

CREATE TABLE IF NOT EXISTS episodes (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    BLOB NOT NULL,
    created_at REAL NOT NULL,
    meta       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id, created_at);

CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    goal        TEXT NOT NULL,
    status      TEXT NOT NULL,
    plan        TEXT,
    results     TEXT NOT NULL DEFAULT '[]',
    answer      TEXT,
    error       TEXT,
    attempt     INTEGER NOT NULL DEFAULT 0,
    pending     TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    id          TEXT NOT NULL UNIQUE,
    ts          REAL NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    tool        TEXT,
    permission  TEXT,
    outcome     TEXT NOT NULL,
    detail      BLOB,
    prev_hash   TEXT NOT NULL,
    entry_hash  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at REAL NOT NULL,
    consumed   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_outbox_unconsumed ON outbox(consumed, created_at);

CREATE TABLE IF NOT EXISTS system_flags (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id         TEXT PRIMARY KEY,
    title      BLOB NOT NULL,
    body       BLOB NOT NULL,
    tags       BLOB NOT NULL,
    source     TEXT NOT NULL DEFAULT 'user',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    deleted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_notes_live ON notes(deleted_at, updated_at DESC);

CREATE TABLE IF NOT EXISTS reminders (
    id         TEXT PRIMARY KEY,
    text       BLOB NOT NULL,
    due_at     REAL,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    deleted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(deleted_at, status, due_at);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA user_version = 2")

    def health(self) -> bool:
        try:
            with self.connection() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False
