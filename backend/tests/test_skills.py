"""Starter skills: web search/read, file search, notes, reminders."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from jarvis.container import Container
from jarvis.skills.files import search_files
from jarvis.skills.web_read import read_url
from jarvis.skills.web_search import brave_search
from jarvis.tools.registry import ApprovalRequired, ToolContext, ToolValidationError


def context(container: Container, **overrides) -> ToolContext:
    settings = overrides.pop("settings", container.settings)
    return ToolContext(
        memory=container.memory,
        settings=settings,
        events=container.events,
        db=container.db,
        box=container.box,
        **overrides,
    )


def with_settings(container: Container, **values):
    settings = container.settings.model_copy(update=values)
    return context(container, settings=settings)


async def test_brave_search_formats_untrusted_results(container: Container) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-subscription-token"] == "test-key"
        assert request.url.params["q"] == "jarvis"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "JARVIS",
                            "url": "https://example.com/jarvis",
                            "description": "An assistant",
                        }
                    ]
                }
            },
        )

    settings = container.settings.model_copy(update={"brave_api_key": SecretStr("test-key")})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await brave_search("jarvis", count=3, settings=settings, client=client)

    assert results == [
        {
            "title": "JARVIS",
            "url": "https://example.com/jarvis",
            "description": "An assistant",
        }
    ]


async def test_brave_search_without_key_fails(container: Container) -> None:
    with pytest.raises(ValueError, match="BRAVE"):
        await brave_search("jarvis", count=3, settings=container.settings)


async def test_read_url_returns_bounded_untrusted_text(container: Container) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body><script>x()</script><p>Hello page</p></body></html>",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await read_url(
            "https://example.com/page",
            settings=container.settings,
            client=client,
            resolver=lambda host, port: ["93.184.216.34"],
        )

    assert result["status"] == 200
    assert "Hello page" in result["text"]
    assert result["untrusted"] is True


async def test_web_read_skill_blocks_localhost(container: Container) -> None:
    result = await container.registry.execute(
        "web.read", {"url": "http://127.0.0.1:8766/health"}, context(container)
    )
    assert result.ok is False
    assert "not publicly routable" in (result.error or "")


async def test_files_search_stays_inside_allowlisted_roots(
    container: Container, tmp_path: Path
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "keep-me.txt").write_text("hello", encoding="utf-8")
    (allowed / "other.txt").write_text("hello", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep-outside.txt").write_text("secret", encoding="utf-8")

    ctx = with_settings(container, file_search_roots=[allowed])
    results = search_files("keep", settings=ctx.settings)

    assert [Path(item["path"]).name for item in results] == ["keep-me.txt"]
    assert all(Path(item["path"]).resolve().is_relative_to(allowed.resolve()) for item in results)


async def test_notes_crud_through_registry(container: Container) -> None:
    ctx = context(container)
    created = await container.registry.execute(
        "notes.create", {"title": "Plan", "body": "buy tea", "tags": ["home"]}, ctx
    )
    assert created.ok, created.error
    note_id = created.output["id"]

    listed = await container.registry.execute("notes.list", {}, ctx)
    assert [note["id"] for note in listed.output] == [note_id]

    updated = await container.registry.execute(
        "notes.update", {"id": note_id, "body": "buy jasmine tea"}, ctx
    )
    assert updated.output["body"] == "buy jasmine tea"

    with pytest.raises(ApprovalRequired):
        await container.registry.execute("notes.delete", {"id": note_id}, ctx)
    deleted = await container.registry.execute("notes.delete", {"id": note_id}, ctx, approved=True)
    assert deleted.output["deleted"] is True
    assert (await container.registry.execute("notes.list", {}, ctx)).output == []


async def test_notes_tools_reject_invalid_args(container: Container) -> None:
    with pytest.raises(ToolValidationError):
        await container.registry.execute("notes.create", {"body": ""}, context(container))


async def test_reminders_lifecycle(container: Container) -> None:
    ctx = context(container)
    due = await container.registry.execute(
        "reminders.create", {"text": "drink tea", "due_at": time.time() - 60}, ctx
    )
    future = await container.registry.execute(
        "reminders.create", {"text": "call mum", "due_at": time.time() + 3600}, ctx
    )
    assert due.ok and future.ok

    pending = await container.registry.execute("reminders.list", {"status": "pending"}, ctx)
    assert {item["id"] for item in pending.output} == {due.output["id"], future.output["id"]}

    done = await container.registry.execute("reminders.complete", {"id": due.output["id"]}, ctx)
    assert done.output["status"] == "done"

    with pytest.raises(ApprovalRequired):
        await container.registry.execute("reminders.delete", {"id": future.output["id"]}, ctx)
    removed = await container.registry.execute(
        "reminders.delete", {"id": future.output["id"]}, ctx, approved=True
    )
    assert removed.output["deleted"] is True


async def test_skill_timeout_is_reported(container: Container, tmp_path: Path) -> None:
    package = tmp_path / "slow"
    package.mkdir()
    (package / "manifest.json").write_text(
        """
        {"name": "slow", "description": "sleeps", "permission": "read_only",
         "timeout_s": 0.05, "input_schema": {"type": "object", "properties": {}}}
        """,
        encoding="utf-8",
    )
    (package / "skill.py").write_text(
        "import asyncio\nasync def run(args, context):\n    await asyncio.sleep(1)\n    return {}\n",
        encoding="utf-8",
    )
    from jarvis.skills.loader import SkillLoader

    SkillLoader(container.registry).load_package(package)

    result = await container.registry.execute("slow", {}, context(container))
    assert result.ok is False
    assert "timed out" in (result.error or "")
