"""The ported security modules wired into the local registry and roster.

These assertions are about the integration, not the scanners themselves: every
ported module must be a registered tool with the right permission tier, the
security agent must be able to reach it, and the source scan must run through
the registry with its own confinement rules intact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.agent.team import ROSTER
from jarvis.config import Settings
from jarvis.container import Container, build_container
from jarvis.security.permissions import PermissionTier
from jarvis.tools.registry import ToolContext

from .conftest import FakeLLM

NEW_TOOLS = {
    "security.source_scan": PermissionTier.READ_ONLY,
    "security.pc_audit": PermissionTier.READ_ONLY,
    "security.defender_scan": PermissionTier.CONFIRM,
    "security.bughunter_status": PermissionTier.READ_ONLY,
    "security.bughunter_classify": PermissionTier.READ_ONLY,
    "security.bughunter_skill": PermissionTier.READ_ONLY,
    "security.bughunter_audit": PermissionTier.READ_ONLY,
    "security.bughunter_triage": PermissionTier.READ_ONLY,
    "security.bughunter_report": PermissionTier.CONFIRM,
    "sandbox.run": PermissionTier.READ_ONLY,
}


def make_settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=root / "data",
        database_path=root / "test.sqlite3",
        project_root=root,
        api_token=None,
        brave_api_key=None,
        ollama_embed_model="",
        capability_probes=False,
        file_search_roots=[],
    )


def make_container(root: Path) -> Container:
    return build_container(make_settings(root), llm=FakeLLM([]), embeddings=None)


def context_for(container: Container) -> ToolContext:
    return ToolContext(
        memory=container.memory,
        settings=container.settings,
        events=container.events,
        db=container.db,
        box=container.box,
    )


def test_every_ported_tool_is_registered_with_its_permission(tmp_path) -> None:
    container = make_container(tmp_path)
    for name, tier in NEW_TOOLS.items():
        assert container.registry.has(name), name
        assert container.registry.get(name).manifest.permission is tier


def test_the_security_agent_can_reach_every_ported_tool(tmp_path) -> None:
    roles = {role.id: role for role in ROSTER}
    assert set(NEW_TOOLS) <= set(roles["security"].tools)


async def test_source_scan_tool_reports_findings_through_the_registry(tmp_path) -> None:
    (tmp_path / "leak.py").write_text('API_KEY = "abcdef1234567890"\n', encoding="utf-8")
    container = make_container(tmp_path)
    result = await container.registry.execute(
        "security.source_scan", {}, context_for(container)
    )
    assert result.ok, result.error
    assert result.output["scanned_files"] >= 1
    assert result.output["summary"]["total_findings"] >= 1
    report = tmp_path / "data" / "security-reports" / "latest.json"
    assert report.is_file()
    assert result.output["report"] == str(report)


async def test_source_scan_tool_refuses_a_root_outside_the_project(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.py").write_text('API_KEY = "abcdef1234567890"\n', encoding="utf-8")
    container = make_container(project)
    result = await container.registry.execute(
        "security.source_scan", {"root": str(outside)}, context_for(container)
    )
    assert result.ok is False
    assert "inside the project root" in (result.error or "")


@pytest.mark.parametrize("name", sorted(NEW_TOOLS))
def test_ported_manifests_describe_themselves(tmp_path, name) -> None:
    manifest = make_container(tmp_path).registry.get(name).manifest
    assert manifest.description
    assert manifest.tags
    assert manifest.input_schema["type"] == "object"
    assert manifest.timeout_s is not None
