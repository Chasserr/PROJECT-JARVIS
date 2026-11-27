"""Encrypted reminder CRUD. Delivery/scheduling arrives in Phase 5."""

from __future__ import annotations

import sqlite3
import time
import uuid

from ..db import Database
from ..security.crypto import SecretBox
from .models import Reminder, ReminderCreate

_CONTEXT = b"reminder"


class ReminderStore:
    def __init__(self, db: Database, box: SecretBox) -> None:
        self._db = db
        self._box = box

    def add(self, data: ReminderCreate) -> Reminder:
        reminder_id = str(uuid.uuid4())
        now = time.time()
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO reminders (id, text, due_at, status, created_at, updated_at)"
                " VALUES (?, ?, ?, 'pending', ?, ?)",
                (reminder_id, self._enc(data.text), data.due_at, now, now),
            )
        return Reminder(
            id=reminder_id,
            text=data.text,
            due_at=data.due_at,
            created_at=now,
            updated_at=now,
        )

    def get(self, reminder_id: str) -> Reminder | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM reminders WHERE id = ? AND deleted_at IS NULL", (reminder_id,)
            ).fetchone()
        return self._row(row) if row else None

    def list(self, *, status: str | None = None, limit: int = 50) -> list[Reminder]:
        query = "SELECT * FROM reminders WHERE deleted_at IS NULL"
        params: list[object] = []
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY due_at IS NULL, due_at, created_at LIMIT ?"
        params.append(max(1, min(limit, 200)))
        with self._db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row(row) for row in rows]

    def due(self, *, now: float | None = None, limit: int = 50) -> list[Reminder]:
        moment = time.time() if now is None else now
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE deleted_at IS NULL AND status = 'pending'"
                " AND due_at IS NOT NULL AND due_at <= ? ORDER BY due_at LIMIT ?",
                (moment, max(1, min(limit, 200))),
            ).fetchall()
        return [self._row(row) for row in rows]

    def complete(self, reminder_id: str) -> Reminder:
        current = self.get(reminder_id)
        if current is None:
            raise KeyError(f"reminder not found: {reminder_id}")
        now = time.time()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE reminders SET status = 'done', updated_at = ? WHERE id = ?",
                (now, reminder_id),
            )
        return current.model_copy(update={"status": "done", "updated_at": now})

    def delete(self, reminder_id: str, *, hard: bool = False) -> bool:
        with self._db.connection() as conn:
            if hard:
                cursor = conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            else:
                cursor = conn.execute(
                    "UPDATE reminders SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                    (time.time(), reminder_id),
                )
            return cursor.rowcount > 0

    def _enc(self, text: str) -> bytes:
        return self._box.encrypt_text(text, context=_CONTEXT)

    def _dec(self, blob: bytes) -> str:
        return self._box.decrypt_text(blob, context=_CONTEXT)

    def _row(self, row: sqlite3.Row) -> Reminder:
        return Reminder(
            id=row["id"],
            text=self._dec(row["text"]),
            due_at=row["due_at"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
