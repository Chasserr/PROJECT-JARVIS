"""Runs interrupted by a core restart must not stay pending forever.

A row still marked ``running`` at startup belongs to a process that died mid-run.
``reap_orphaned_runs`` closes those, and ``create_app`` calls it on startup so the
dashboard's active-task count can return to zero with an explanation attached.
"""

from __future__ import annotations

import json
import time

from jarvis.api.app import create_app
from jarvis.config import Settings
from jarvis.container import build_container

from .conftest import FakeLLM


def make_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        database_path=tmp_path / "test.sqlite3",
        api_token=None,
        ollama_embed_model="",
        capability_probes=False,
    )


def _find(container, run_id: str):
    return next(r for r in container.agent.list_runs(200) if r.run_id == run_id)


def _insert_run(container, run_id: str, status: str) -> None:
    """Insert a row exactly as the loop stores one (fields are encrypted)."""

    def enc(value) -> str:
        return container.box.encrypt_text(json.dumps(value), context=b"run").hex()

    now = time.time()
    with container.db.connection() as conn:
        conn.execute(
            """
            INSERT INTO runs (id, session_id, goal, status, plan, results, attempt,
                              created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, "default", enc("Call desktop.status once"), status, enc({}), enc([]), 0, now, now),
        )


def test_orphaned_running_row_is_closed_and_explained(tmp_path):
    container = build_container(make_settings(tmp_path), llm=FakeLLM([]), embeddings=None)
    _insert_run(container, "11111111-1111-4111-8111-111111111111", "running")

    assert container.agent.reap_orphaned_runs() == 1

    run = _find(container, "11111111-1111-4111-8111-111111111111")
    assert run.status == "failed"
    assert "interrupted" in (run.error or "")


def test_completed_and_failed_rows_are_untouched(tmp_path):
    container = build_container(make_settings(tmp_path), llm=FakeLLM([]), embeddings=None)
    _insert_run(container, "22222222-2222-4222-8222-222222222222", "completed")
    _insert_run(container, "33333333-3333-4333-8333-333333333333", "failed")

    assert container.agent.reap_orphaned_runs() == 0
    assert _find(container, "22222222-2222-4222-8222-222222222222").status == "completed"
    assert _find(container, "33333333-3333-4333-8333-333333333333").status == "failed"


def test_app_startup_reaps_orphans(tmp_path):
    """create_app itself must leave no run stuck in running."""
    settings = make_settings(tmp_path)
    first = build_container(settings, llm=FakeLLM([]), embeddings=None)
    _insert_run(first, "44444444-4444-4444-8444-444444444444", "running")

    app = create_app(settings, llm=FakeLLM([]), embeddings=None)
    run = _find(app.state.container, "44444444-4444-4444-8444-444444444444")
    assert run.status == "failed"
    assert "interrupted" in (run.error or "")
