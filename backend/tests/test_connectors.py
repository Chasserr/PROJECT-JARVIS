"""Connector tests: real files on disk, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.config import Settings
from jarvis.connectors.base import Connector, SourceError, SourceHit, SourceState, SourceStatus
from jarvis.connectors.local import LocalFilesConnector, ObsidianConnector, ProjectRepoConnector
from jarvis.connectors.registry import ConnectorRegistry


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "environment": "test",
        "data_dir": tmp_path / "data",
        "database_path": tmp_path / "test.sqlite3",
        "api_token": None,
        "brave_api_key": None,
        "ollama_embed_model": "",
        "capability_probes": False,
        "connector_timeout_s": 5.0,
        # The host shell may export real roots; tests must not inherit them.
        "file_search_roots": [],
        "connector_allowlist": [],
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "roadmap.md").write_text("# Roadmap\n\nShip the connector layer.", encoding="utf-8")
    (root / "notes.txt").write_text("nothing relevant here", encoding="utf-8")
    (root / "binary.bin").write_bytes(b"\x00\x01\x02")
    return root


def test_local_files_reports_not_configured_without_roots(tmp_path: Path) -> None:
    connector = LocalFilesConnector(make_settings(tmp_path))
    status = connector.status()
    assert status.state is SourceState.NOT_CONFIGURED
    assert "JARVIS_FILE_SEARCH_ROOTS" in status.detail


@pytest.mark.asyncio
async def test_local_files_search_matches_name_and_content(tmp_path: Path, docs: Path) -> None:
    connector = LocalFilesConnector(make_settings(tmp_path, file_search_roots=[docs]))
    assert connector.status().state is SourceState.CONNECTED

    by_name = await connector.search("roadmap", limit=5)
    assert [hit.title for hit in by_name] == ["roadmap.md"]
    assert by_name[0].source == "local_files"
    assert by_name[0].metadata["match"] == "filename"

    by_content = await connector.search("connector layer", limit=5)
    assert by_content and by_content[0].title == "roadmap.md"
    assert "connector layer" in by_content[0].snippet.lower()


@pytest.mark.asyncio
async def test_local_files_read_returns_text_and_refuses_escape(
    tmp_path: Path, docs: Path
) -> None:
    connector = LocalFilesConnector(make_settings(tmp_path, file_search_roots=[docs]))
    payload = await connector.read(str(docs / "roadmap.md"), max_chars=500)
    assert "Ship the connector layer" in payload["text"]

    with pytest.raises(SourceError, match="outside every authorised root"):
        await connector.read(str(tmp_path / "test.sqlite3"), max_chars=500)


@pytest.mark.asyncio
async def test_local_files_read_refuses_binary(tmp_path: Path, docs: Path) -> None:
    connector = LocalFilesConnector(make_settings(tmp_path, file_search_roots=[docs]))
    with pytest.raises(SourceError, match="not a text format"):
        await connector.read(str(docs / "binary.bin"), max_chars=100)


@pytest.mark.asyncio
async def test_project_repo_searches_code(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("def handler():\n    return 'needle-42'\n", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "skip.js").write_text("needle-42", encoding="utf-8")

    connector = ProjectRepoConnector(make_settings(tmp_path, project_root=repo))
    hits = await connector.search("needle-42", limit=5)
    assert len(hits) == 1
    assert hits[0].title == "src/app.py"
    assert hits[0].source == "project_repo"


@pytest.mark.asyncio
async def test_obsidian_requires_a_vault_and_finds_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Idea.md").write_text("# Launch idea\n\n#product #q4\n", encoding="utf-8")

    unset = ObsidianConnector(make_settings(tmp_path))
    assert unset.status().state is SourceState.NOT_CONFIGURED

    connector = ObsidianConnector(make_settings(tmp_path, obsidian_vault=vault))
    hits = await connector.search("launch", limit=5)
    assert hits[0].title == "Launch idea"
    assert hits[0].metadata["tags"] == ["product", "q4"]


class _Boom(Connector):
    id = "boom"
    label = "Broken source"
    kind = "test"

    def status(self) -> SourceStatus:
        return SourceStatus(SourceState.CONNECTED, "pretends to work")

    async def search(self, query: str, *, limit: int) -> list[SourceHit]:
        raise SourceError("backend refused the query")


class _Fixed(Connector):
    id = "fixed"
    label = "Working source"
    kind = "test"

    def status(self) -> SourceStatus:
        return SourceStatus(SourceState.CONNECTED, "ok")

    async def search(self, query: str, *, limit: int) -> list[SourceHit]:
        return [
            SourceHit(source=self.id, title="hit one", locator="a"),
            SourceHit(source="impostor", title="wrong attribution", locator="b"),
        ]


@pytest.mark.asyncio
async def test_registry_isolates_failures_and_keeps_attribution() -> None:
    registry = ConnectorRegistry(timeout_s=5.0)
    registry.register(_Boom())
    registry.register(_Fixed())

    result = await registry.search("anything")
    assert [hit["title"] for hit in result["hits"]] == ["hit one"]
    assert result["hits"][0]["source"] == "fixed"
    assert result["errors"] == [{"source": "boom", "error": "backend refused the query"}]
    states = {item["id"]: item["state"] for item in result["sources"]}
    assert states == {"boom": "error", "fixed": "connected"}


@pytest.mark.asyncio
async def test_registry_allowlist_blocks_unauthorised_source() -> None:
    registry = ConnectorRegistry(allowlist=["fixed"], timeout_s=5.0)
    registry.register(_Boom())
    registry.register(_Fixed())

    described = {item["id"]: item for item in registry.describe()}
    assert described["boom"]["state"] == "not_configured"
    assert "JARVIS_CONNECTOR_ALLOWLIST" in described["boom"]["detail"]

    result = await registry.search("x")
    assert [hit["source"] for hit in result["hits"]] == ["fixed"]

    with pytest.raises(SourceError):
        await registry.read("boom", "anything")


@pytest.mark.asyncio
async def test_registry_reports_when_nothing_is_authorised() -> None:
    registry = ConnectorRegistry(allowlist=[], timeout_s=5.0)
    registry.register(_Fixed())
    result = await registry.search("x")
    assert result["hits"] == []
    assert result["note"] == "no authorised source is configured"
