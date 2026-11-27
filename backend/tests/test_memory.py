from __future__ import annotations

from jarvis.container import Container
from jarvis.memory.models import MemoryCreate, MemoryKind


async def test_memory_roundtrip_and_encryption(container: Container) -> None:
    memory = await container.memory.add(
        MemoryCreate(content="My favourite tea is jasmine", kind=MemoryKind.PREFERENCE)
    )
    fetched = container.memory.get(memory.id)
    assert fetched is not None
    assert fetched.content == "My favourite tea is jasmine"

    with container.db.connection() as conn:
        raw = conn.execute("SELECT content FROM memories WHERE id = ?", (memory.id,)).fetchone()[
            "content"
        ]
    assert b"jasmine" not in raw
    assert container.box.decrypt_text(raw, context=b"memory") == "My favourite tea is jasmine"


async def test_search_prefers_matching_memory(container: Container) -> None:
    await container.memory.add(MemoryCreate(content="The deploy key lives in the vault"))
    await container.memory.add(MemoryCreate(content="I like oat milk in coffee"))
    results = await container.memory.search("vault key", 5)
    assert results
    assert "vault" in results[0].content
    assert results[0].score is not None


async def test_soft_delete_then_purge(container: Container) -> None:
    memory = await container.memory.add(MemoryCreate(content="temporary note"))
    assert container.memory.delete(memory.id) is True
    assert container.memory.get(memory.id) is None
    assert container.memory.delete(memory.id, hard=True) is True
    with container.db.connection() as conn:
        row = conn.execute("SELECT id FROM memories WHERE id = ?", (memory.id,)).fetchone()
    assert row is None


async def test_episodes_are_encrypted(container: Container) -> None:
    container.memory.add_episode("s1", "user", "secret chat content")
    episodes = container.memory.episodes("s1")
    assert episodes[0]["content"] == "secret chat content"
    with container.db.connection() as conn:
        raw = conn.execute("SELECT content FROM episodes").fetchone()["content"]
    assert b"secret chat content" not in raw
