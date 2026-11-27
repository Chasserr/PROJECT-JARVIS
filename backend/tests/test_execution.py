"""Execution tool tests: allowlists, containment, no browser launches."""

from __future__ import annotations

import sys
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
        file_write_roots=[tmp_path],
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
async def test_shell_runs_allowlisted_command(tmp_path: Path) -> None:
    container = make_container(tmp_path)
    result = await container.registry.execute(
        "shell.run",
        {"argv": [sys.executable, "-c", "print('hello-from-shell')"]},
        context(container),
        approved=True,
    )
    assert result.ok, result.error
    assert result.output["exit_code"] == 0
    assert "hello-from-shell" in result.output["stdout"]


@pytest.mark.asyncio
async def test_shell_requires_approval(tmp_path: Path) -> None:
    container = make_container(tmp_path)
    with pytest.raises(ApprovalRequired):
        await container.registry.execute(
            "shell.run", {"argv": [sys.executable, "-c", "print(1)"]}, context(container)
        )


@pytest.mark.asyncio
async def test_shell_refuses_unlisted_command(tmp_path: Path) -> None:
    container = make_container(tmp_path)
    result = await container.registry.execute(
        "shell.run", {"argv": ["curl", "https://example.com"]}, context(container), approved=True
    )
    assert not result.ok
    assert "not allowlisted" in (result.error or "")


@pytest.mark.asyncio
async def test_shell_refuses_cwd_outside_project(tmp_path: Path) -> None:
    container = make_container(tmp_path)
    result = await container.registry.execute(
        "shell.run",
        {"argv": [sys.executable, "-c", "print(1)"], "cwd": str(tmp_path.parent)},
        context(container),
        approved=True,
    )
    assert not result.ok
    assert "outside the project root" in (result.error or "")


@pytest.mark.asyncio
async def test_files_write_inside_root(tmp_path: Path) -> None:
    container = make_container(tmp_path)
    with pytest.raises(ApprovalRequired):
        await container.registry.execute(
            "files.write", {"path": "out.txt", "content": "x"}, context(container)
        )

    result = await container.registry.execute(
        "files.write",
        {"path": "nested/out.txt", "content": "hello\nworld\n"},
        context(container),
        approved=True,
    )
    assert result.ok, result.error
    target = tmp_path / "nested" / "out.txt"
    assert target.read_text(encoding="utf-8") == "hello\nworld\n"
    assert result.output["created"] is True


@pytest.mark.asyncio
async def test_files_write_refuses_escape_and_git(tmp_path: Path) -> None:
    container = make_container(tmp_path)
    outside = await container.registry.execute(
        "files.write",
        {"path": str(tmp_path.parent / "escaped.txt"), "content": "nope"},
        context(container),
        approved=True,
    )
    assert not outside.ok
    assert "outside every writable root" in (outside.error or "")

    git = await container.registry.execute(
        "files.write", {"path": ".git/config", "content": "nope"}, context(container), approved=True
    )
    assert not git.ok
    assert ".git" in (git.error or "")


@pytest.mark.asyncio
async def test_browser_blocks_private_hosts_without_launching(tmp_path: Path) -> None:
    container = make_container(tmp_path, browser_allowed_domains=["localhost"])
    result = await container.registry.execute(
        "browser.open", {"url": "http://localhost:8765/"}, context(container)
    )
    assert not result.ok
    assert "non-public host" in (result.error or "")


def test_new_tools_reach_the_roles_that_need_them(tmp_path: Path) -> None:
    container = make_container(tmp_path)
    team = container.agent.team
    for name in ("shell.run", "files.write", "browser.open", "sources.search", "email.send"):
        assert container.registry.has(name), name

    engineer = {item.name for item in team.manifests_for(team.get("engineer"))}
    assert {"shell.run", "files.write"} <= engineer

    testing = {item.name for item in team.manifests_for(team.get("testing"))}
    assert "shell.run" in testing

    browser = {item.name for item in team.manifests_for(team.get("browser"))}
    assert "browser.open" in browser


@pytest.mark.asyncio
async def test_browser_blocks_domains_off_the_allowlist(tmp_path: Path) -> None:
    container = make_container(tmp_path, browser_allowed_domains=[])
    result = await container.registry.execute(
        "browser.open", {"url": "https://example.com/"}, context(container)
    )
    assert not result.ok
    assert "not authorised" in (result.error or "")
