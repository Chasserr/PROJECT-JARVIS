from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from jarvis.memory.protection import _PREFIX, protect_text, unprotect_text


class MemoryStore:
    """SQLite memory with Windows DPAPI encryption for stored memory content."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    id TEXT PRIMARY KEY,
                    request TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_tasks_updated ON agent_tasks(updated_at);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
                CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);
            """)
            # One-time migration: protect any content written by the earlier plaintext prototype.
            rows = conn.execute("SELECT id, content FROM memories").fetchall()
            for row in rows:
                if not row["content"].startswith(_PREFIX):
                    conn.execute("UPDATE memories SET content=? WHERE id=?",
                                 (protect_text(row["content"]), row["id"]))

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        if not key or len(key) > 100 or len(value) > 500:
            raise ValueError("setting key/value is invalid")
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                   updated_at=excluded.updated_at""",
                (key, value, datetime.now(UTC).isoformat()),
            )

    def add_memory(self, content: str, *, kind: str = "fact", source: str = "user",
                   tags: list[str] | None = None) -> dict[str, Any]:
        value = content.strip()
        if not value or len(value) > 10_000:
            raise ValueError("memory must contain 1–10000 characters")
        now = datetime.now(UTC).isoformat()
        item = {"id": uuid4().hex, "kind": kind, "content": value, "source": source,
                "tags": tags or [], "created_at": now, "updated_at": now}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memories(id,kind,content,source,tags_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (item["id"], kind, protect_text(value), source, json.dumps(item["tags"]), now, now),
            )
        return item

    def list_memories(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"id": r["id"], "kind": r["kind"], "content": unprotect_text(r["content"]),
                 "source": r["source"], "tags": json.loads(r["tags_json"]),
                 "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in rows]

    def delete_memory(self, memory_id: str) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE memories SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
                (now, now, memory_id),
            )
        return result.rowcount == 1

    def audit(self, *, actor: str, action: str, resource: str, decision: str,
              reason: str = "", correlation_id: str = "", metadata: dict[str, Any] | None = None) -> str:
        event_id = uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?,?)",
                (event_id, actor, action, resource, decision, reason, correlation_id,
                 json.dumps(metadata or {}, ensure_ascii=False), datetime.now(UTC).isoformat()),
            )
        return event_id

    def list_audit(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) | {"metadata": json.loads(r["metadata_json"])} for r in rows]


    def search_memories(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        terms = [term.casefold() for term in query.split() if len(term) > 1]
        if not terms:
            raise ValueError("memory search query must contain at least one meaningful word")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        # Search decrypted content in-process; encrypted values are never indexed in plaintext.
        ranked = []
        for item in self.list_memories(limit=500):
            haystack = (item["content"] + " " + item["kind"] + " " +
                        " ".join(item["tags"])).casefold()
            score = sum(1 for term in terms if term in haystack)
            if score:
                ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[:limit]]


    def save_task(self, task: dict[str, Any]) -> None:
        required = {"id", "request", "status", "steps", "results", "error"}
        if not required.issubset(task):
            raise ValueError("task record is incomplete")
        now = datetime.now(UTC).isoformat()
        payload = json.dumps(task, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO agent_tasks(id, request, status, payload, updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                   payload=excluded.payload, updated_at=excluded.updated_at""",
                (task["id"], task["request"], task["status"], payload, now),
            )

    def list_tasks(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM agent_tasks ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]
