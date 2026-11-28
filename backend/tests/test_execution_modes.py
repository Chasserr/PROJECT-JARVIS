"""Execution modes: policy matrix, persistence and run-level gating.

These tests drive the real AgentLoop with a scripted planner so each mode's
behaviour is proven at the point where tools actually run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.agent.models import RunStatus
from jarvis.container import Container
from jarvis.security.modes import (
    DEFAULT_MODE,
    ExecutionMode,
    ModeStore,
    auto_approved,
    requires_approval,
)
from jarvis.security.permissions import PermissionTier
from jarvis.tools.manifest import ToolManifest

from .conftest import FakeLLM


def _fake(container: Container) -> FakeLLM:
    assert isinstance(container.llm, FakeLLM)
    return container.llm


def _plan(*steps: dict) -> str:
    return json.dumps({"summary": "plan", "steps": list(steps)})


def _manifest(tier: PermissionTier, *, dangerous: bool = False) -> ToolManifest:
    return ToolManifest(
        name="test.tool",
        description="manifest used to score the mode policy",
        permission=tier,
        dangerous=dangerous,
    )


# --------------------------------------------------------------------------- policy


def test_mode_matrix_for_read_only_tool() -> None:
    manifest = _manifest(PermissionTier.READ_ONLY)
    assert requires_approval(ExecutionMode.MANUAL, manifest, PermissionTier.READ_ONLY) is True
    assert requires_approval(ExecutionMode.SUPERVISED, manifest, PermissionTier.READ_ONLY) is False
    assert requires_approval(ExecutionMode.AUTONOMOUS, manifest, PermissionTier.READ_ONLY) is False


def test_mode_matrix_for_confirm_tool() -> None:
    manifest = _manifest(PermissionTier.CONFIRM)
    assert requires_approval(ExecutionMode.MANUAL, manifest, PermissionTier.CONFIRM) is True
    assert requires_approval(ExecutionMode.SUPERVISED, manifest, PermissionTier.CONFIRM) is True
    assert requires_approval(ExecutionMode.AUTONOMOUS, manifest, PermissionTier.CONFIRM) is False
    assert auto_approved(ExecutionMode.AUTONOMOUS, manifest, PermissionTier.CONFIRM) is True
    assert auto_approved(ExecutionMode.SUPERVISED, manifest, PermissionTier.CONFIRM) is False


def test_dangerous_tool_pauses_in_every_mode() -> None:
    manifest = _manifest(PermissionTier.CONFIRM, dangerous=True)
    for mode in ExecutionMode:
        assert requires_approval(mode, manifest, PermissionTier.CONFIRM) is True
        assert auto_approved(mode, manifest, PermissionTier.CONFIRM) is False


def test_policy_override_lowers_prompting_in_supervised_mode() -> None:
    """A tool the user demoted to read_only no longer prompts when supervised."""
    manifest = _manifest(PermissionTier.CONFIRM)
    assert requires_approval(ExecutionMode.SUPERVISED, manifest, PermissionTier.CONFIRM) is True
    assert requires_approval(ExecutionMode.SUPERVISED, manifest, PermissionTier.READ_ONLY) is False


# ----------------------------------------------------------------------- persistence


def test_mode_store_round_trip(tmp_path: Path) -> None:
    store = ModeStore(tmp_path / "agent-mode.json")
    assert store.get() is DEFAULT_MODE
    store.set(ExecutionMode.AUTONOMOUS)
    assert ModeStore(tmp_path / "agent-mode.json").get() is ExecutionMode.AUTONOMOUS
    store.set(ExecutionMode.MANUAL)
    assert store.get() is ExecutionMode.MANUAL


def test_mode_store_falls_back_on_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "agent-mode.json"
    path.write_text("{not json", encoding="utf-8")
    assert ModeStore(path).get() is DEFAULT_MODE
    path.write_text(json.dumps({"mode": "turbo"}), encoding="utf-8")
    assert ModeStore(path).get() is DEFAULT_MODE


# --------------------------------------------------------------------- loop gating


async def test_autonomous_run_skips_confirm_pause(container: Container) -> None:
    container.mode_store.set(ExecutionMode.AUTONOMOUS)
    _fake(container).responses = [
        _plan({"tool": "memory.forget", "args": {"id": "missing-id"}}),
        json.dumps({"done": True, "reason": "forget attempted"}),
        "Done.",
    ]
    result = await container.agent.start("Forget that memory")
    assert result.status is RunStatus.COMPLETED, result
    assert not result.approval
    assert len(result.steps) == 1


async def test_supervised_run_pauses_on_confirm_tool(container: Container) -> None:
    container.mode_store.set(ExecutionMode.SUPERVISED)
    _fake(container).responses = [_plan({"tool": "memory.forget", "args": {"id": "missing-id"}})]
    result = await container.agent.start("Forget that memory")
    assert result.status is RunStatus.AWAITING_APPROVAL
    assert result.approval is not None
    assert result.approval.tool == "memory.forget"


async def test_manual_run_pauses_on_read_only_tool(container: Container) -> None:
    container.mode_store.set(ExecutionMode.MANUAL)
    _fake(container).responses = [_plan({"tool": "time.now", "args": {"timezone": "UTC"}})]
    result = await container.agent.start("What time is it?")
    assert result.status is RunStatus.AWAITING_APPROVAL
    assert result.approval is not None
    assert result.approval.tool == "time.now"


async def test_manual_run_pauses_between_steps(container: Container) -> None:
    container.mode_store.set(ExecutionMode.MANUAL)
    _fake(container).responses = [
        _plan(
            {"tool": "time.now", "args": {"timezone": "UTC"}},
            {"tool": "time.now", "args": {"timezone": "Europe/London"}},
        )
    ]
    first = await container.agent.start("Compare two clocks")
    assert first.status is RunStatus.AWAITING_APPROVAL
    assert first.approval is not None and first.approval.step_index == 0

    second = await container.agent.resume(first.run_id, approved=True)
    assert second.status is RunStatus.AWAITING_APPROVAL
    assert second.approval is not None and second.approval.step_index == 1
    assert len(second.steps) == 1, "only the approved step should have run"

    _fake(container).responses = [
        json.dumps({"done": True, "reason": "both clocks read"}),
        "Both clocks are read.",
    ]
    third = await container.agent.resume(second.run_id, approved=True)
    assert third.status is RunStatus.COMPLETED
    assert len(third.steps) == 2


async def test_dangerous_tool_still_pauses_in_autonomous(container: Container) -> None:
    container.mode_store.set(ExecutionMode.AUTONOMOUS)
    _fake(container).responses = [
        _plan({"tool": "camera.analyze", "args": {"prompt": "describe the scene"}})
    ]
    result = await container.agent.start("Look through the camera")
    assert result.status is RunStatus.AWAITING_APPROVAL
    assert result.approval is not None
    assert result.approval.tool == "camera.analyze"


async def test_run_audit_records_the_mode(container: Container) -> None:
    container.mode_store.set(ExecutionMode.MANUAL)
    _fake(container).responses = [_plan({"tool": "time.now", "args": {"timezone": "UTC"}})]
    await container.agent.start("What time is it?")
    entries = [entry for entry in container.audit.tail(50) if entry.action == "run.started"]
    assert entries, "run.started should be audited"
    assert entries[0].detail["mode"] == "manual"
