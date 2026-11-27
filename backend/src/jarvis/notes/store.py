"""Encrypted note CRUD backed by SQLite."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid

from ..db import Database
from ..security.crypto import SecretBox
from .models import Note, NoteCreate, NoteUpdate

_CONTEXT = b"note"


class NoteStore:
    def __init__(self, db: Database, box: SecretBox) -> None:
        self._db = db
        self._box = box

    def add(self, data: NoteCreate, *, source: str = "user") -> Note:
        note_id = str(uuid.uuid4())
        now = time.time()
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO notes (id, title, body, tags, source, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    note_id,
                    self._enc(data.title),
                    self._enc(data.body),
                    self._enc(json.dumps(data.tags)),
                    source,
                    now,
                    now,
                ),
            )
        return Note(
            id=note_id,
            title=data.title,
            body=data.body,
            tags=data.tags,
            created_at=now,
            updated_at=now,
        )

    def get(self, note_id: str) -> Note | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM notes WHERE id = ? AND deleted_at IS NULL", (note_id,)
            ).fetchone()
        return self._row(row) if row else None

    def list(self, limit: int = 20) -> list[Note]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM notes WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._row(row) for row in rows]

    def update(self, note_id: str, data: NoteUpdate) -> Note:
        current = self.get(note_id)
        if current is None:
            raise KeyError(f"note not found: {note_id}")
        title = data.title if data.title is not None else current.title
        body = data.body if data.body is not None else current.body
        tags = data.tags if data.tags is not None else current.tags
        now = time.time()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE notes SET title = ?, body = ?, tags = ?, updated_at = ? WHERE id = ?",
                (self._enc(title), self._enc(body), self._enc(json.dumps(tags)), now, note_id),
            )
        return Note(
            id=note_id,
            title=title,
            body=body,
            tags=tags,
            created_at=current.created_at,
            updated_at=now,
        )

    def delete(self, note_id: str, *, hard: bool = False) -> bool:
        with self._db.connection() as conn:
            if hard:
                cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            else:
                cursor = conn.execute(
                    "UPDATE notes SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                    (time.time(), note_id),
                )
            return cursor.rowcount > 0

    def _enc(self, text: str) -> bytes:
        return self._box.encrypt_text(text, context=_CONTEXT)

    def _dec(self, blob: bytes) -> str:
        return self._box.decrypt_text(blob, context=_CONTEXT)

    def _row(self, row: sqlite3.Row) -> Note:
        return Note(
            id=row["id"],
            title=self._dec(row["title"]),
            body=self._dec(row["body"]),
            tags=json.loads(self._dec(row["tags"])),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
