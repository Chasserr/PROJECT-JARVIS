import os
import sqlite3

import pytest

from jarvis.memory.protection import _PREFIX, protect_text, unprotect_text
from jarvis.memory.store import MemoryStore

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI is required")


def test_dpapi_round_trip() -> None:
    secret = "private JARVIS memory — test"
    encrypted = protect_text(secret)
    assert encrypted.startswith(_PREFIX)
    assert secret not in encrypted
    assert unprotect_text(encrypted) == secret


def test_memory_content_is_encrypted_at_rest(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    store = MemoryStore(db_path)
    secret = "a private test phrase"
    saved = store.add_memory(secret)
    with sqlite3.connect(db_path) as conn:
        raw = conn.execute("SELECT content FROM memories WHERE id=?", (saved["id"],)).fetchone()[0]
    assert raw.startswith(_PREFIX)
    assert secret not in raw
    assert store.list_memories()[0]["content"] == secret


def test_plaintext_legacy_rows_are_migrated(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    MemoryStore(db_path)
    now = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO memories(id,kind,content,source,tags_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            ("legacy", "fact", "legacy secret", "user", "[]", now, now),
        )
    migrated = MemoryStore(db_path)
    with sqlite3.connect(db_path) as conn:
        raw = conn.execute("SELECT content FROM memories WHERE id='legacy'").fetchone()[0]
    assert raw.startswith(_PREFIX)
    assert migrated.list_memories()[0]["content"] == "legacy secret"
