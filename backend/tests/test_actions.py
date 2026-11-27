"""Action tests: drafts, approval gating, real report files, no live SMTP."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.config import Settings
from jarvis.container import build_container
from jarvis.llm.base import LLMError
from jarvis.tools.registry import ApprovalRequired, ToolContext


class _NullLLM:
    model = "null"

    async def complete(self, messages, **kwargs):
        raise LLMError("no model is used in these tests")


def make_container(tmp_path: Path, **overrides):
    settings = Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        database_path=tmp_path / "test.sqlite3",
        api_token=None,
        brave_api_key=None,
        ollama_embed_model="",
        capability_probes=False,
        project_root=tmp_path,
        **overrides,
    )
    return build_container(settings, llm=_NullLLM(), embeddings=None)


def context(container) -> ToolContext:
    return ToolContext(
        memory=container.memory,
        settings=container.settings,
        events=container.events,
        db=container.db,
        box=container.box,
    )


@pytest.mark.asyncio
async def test_email_draft_never_claims_to_send(tmp_path: Path) -> None:
    container = make_container(tmp_path)
    result = await container.registry.execute(
        "email.draft",
        {"to": "a@example.com", "subject": "Hello", "body": "Body text"},
        context(container),
    )
    assert result.ok
    assert result.output["sent"] is False
    assert result.output["to"] == ["a@example.com"]
    assert result.output["status"] == "draft"


@pytest.mark.asyncio
async def test_email_draft_rejects_invalid_address(tmp_path: Path) -> None:
    container = make_container(tmp_path)
    result = await container.registry.execute(
        "email.draft",
        {"to": "not-an-address", "subject": "x", "body": "y"},
        context(container),
    )
    assert not result.ok
    assert "not a valid email address" in (result.error or "")


@pytest.mark.asyncio
async def test_email_send_requires_approval_before_any_side_effect(tmp_path: Path) -> None:
    container = make_container(tmp_path)
    with pytest.raises(ApprovalRequired):
        await container.registry.execute(
            "email.send",
            {"to": "a@example.com", "subject": "Hello", "body": "Body"},
            context(container),
        )


@pytest.mark.asyncio
async def test_email_send_reports_missing_smtp_instead_of_faking_success(tmp_path: Path) -> None:
    # A sender is configured but no SMTP host is: the send must fail loudly.
    container = make_container(tmp_path, email_user="jarvis@example.com")
    result = await container.registry.execute(
        "email.send",
        {"to": "a@example.com", "subject": "Hello", "body": "Body"},
        context(container),
        approved=True,
    )
    assert not result.ok
    assert "SMTP is not configured" in (result.error or "")


@pytest.mark.asyncio
async def test_report_generate_writes_a_real_file(tmp_path: Path) -> None:
    container = make_container(tmp_path)
    with pytest.raises(ApprovalRequired):
        await container.registry.execute(
            "report.generate",
            {"title": "Weekly", "sections": [{"heading": "Summary", "body": "All good"}]},
            context(container),
        )

    result = await container.registry.execute(
        "report.generate",
        {
            "title": "Weekly Status",
            "sections": [
                {"heading": "Summary", "body": "All good"},
                {"heading": "Next", "body": "Ship it"},
            ],
            "sources": ["memory:abc"],
        },
        context(container),
        approved=True,
    )
    assert result.ok
    path = Path(result.output["path"])
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "# Weekly Status" in text
    assert "## Summary" in text
    assert "- memory:abc" in text
    assert result.output["bytes"] == len(text.encode("utf-8"))
