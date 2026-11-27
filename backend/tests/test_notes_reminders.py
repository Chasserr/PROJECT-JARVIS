"""Encrypted notes and reminders stores (Phase 2)."""

from __future__ import annotations

import time

from jarvis.db import Database
from jarvis.notes.models import NoteCreate, NoteUpdate
from jarvis.notes.store import NoteStore
from jarvis.reminders.models import ReminderCreate
from jarvis.reminders.store import ReminderStore
from jarvis.security.crypto import SecretBox


def test_note_round_trip_and_ciphertext_at_rest(db: Database, box: SecretBox) -> None:
    store = NoteStore(db, box)
    note = store.add(NoteCreate(title="Groceries", body="jasmine tea and oat milk", tags=["home"]))

    loaded = store.get(note.id)
    assert loaded is not None
    assert loaded.title == "Groceries"
    assert loaded.body == "jasmine tea and oat milk"
    assert loaded.tags == ["home"]

    with db.connection() as conn:
        row = conn.execute("SELECT title, body FROM notes WHERE id = ?", (note.id,)).fetchone()
    assert b"Groceries" not in row["title"]
    assert b"jasmine" not in row["body"]


def test_note_update_and_soft_delete(db: Database, box: SecretBox) -> None:
    store = NoteStore(db, box)
    note = store.add(NoteCreate(body="first draft"))

    updated = store.update(note.id, NoteUpdate(body="second draft", tags=["edited"]))
    assert updated.body == "second draft"
    assert updated.tags == ["edited"]

    assert store.delete(note.id) is True
    assert store.get(note.id) is None
    assert store.list() == []

    assert store.delete(note.id, hard=True) is True


def test_reminder_due_and_completion(db: Database, box: SecretBox) -> None:
    store = ReminderStore(db, box)
    past = store.add(ReminderCreate(text="drink tea", due_at=time.time() - 60))
    future = store.add(ReminderCreate(text="call mum", due_at=time.time() + 3600))

    due_ids = [reminder.id for reminder in store.due(now=time.time())]
    assert due_ids == [past.id]

    completed = store.complete(past.id)
    assert completed.status == "done"
    assert store.due(now=time.time()) == []
    assert [reminder.id for reminder in store.list(status="pending")] == [future.id]

    with db.connection() as conn:
        row = conn.execute("SELECT text FROM reminders WHERE id = ?", (future.id,)).fetchone()
    assert b"call mum" not in row["text"]
