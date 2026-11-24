from jarvis.memory.store import MemoryStore


def test_memory_add_list_delete(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    item = store.add_memory("User prefers local-first AI.", tags=["preference"])
    assert item["content"] == "User prefers local-first AI."
    assert store.list_memories()[0]["id"] == item["id"]
    assert store.delete_memory(item["id"]) is True
    assert store.list_memories() == []
    assert store.delete_memory(item["id"]) is False


def test_memory_rejects_empty_and_oversized(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    for value in (" ", "x" * 10001):
        try:
            store.add_memory(value)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid memory accepted")


def test_audit_event_persists(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    event_id = store.audit(actor="test", action="skill.run", resource="notes",
                           decision="deny", reason="approval required")
    assert store.list_audit()[0]["id"] == event_id


def test_memory_search_ranks_matching_terms(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.add_memory("User prefers local-first JARVIS development.", tags=["preference"])
    store.add_memory("User likes cinematic video editing.")
    results = store.search_memories("local-first JARVIS")
    assert len(results) == 1
    assert "local-first" in results[0]["content"]


def test_memory_search_rejects_empty_query(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.search_memories("  ")
    except ValueError:
        pass
    else:
        raise AssertionError("empty search query accepted")

def test_agent_task_store_round_trip(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    record = {
        "id": "task-123", "request": "Check PC status", "status": "completed",
        "steps": [{"description": "Read status", "tool": None}],
        "results": [{"step": 0, "ok": True}], "error": None,
    }
    store.save_task(record)
    assert store.list_tasks()[0] == record


def test_agent_task_store_updates_existing_task(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    record = {
        "id": "task-123", "request": "Check PC status", "status": "running",
        "steps": [], "results": [], "error": None,
    }
    store.save_task(record)
    record["status"] = "completed"
    store.save_task(record)
    assert store.list_tasks()[0]["status"] == "completed"
