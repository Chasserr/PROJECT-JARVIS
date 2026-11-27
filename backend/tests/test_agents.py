"""Specialist agent team: roster integrity, per-role execution, and collaboration."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from jarvis.agent.loop import RunError
from jarvis.agent.models import RunStatus
from jarvis.agent.team import ORCHESTRATOR_ID, ROSTER
from jarvis.api.app import create_app
from jarvis.config import Settings
from jarvis.container import Container
from jarvis.security.kill_switch import KillSwitchEngaged
from jarvis.tools.agent_tools import _delegate as delegate_tool
from jarvis.tools.registry import ToolContext

from .conftest import FakeLLM

SPECIALISTS = [role for role in ROSTER if role.id != ORCHESTRATOR_ID]
SPECIALIST_IDS = [role.id for role in SPECIALISTS]


def _fake(container: Container) -> FakeLLM:
    assert isinstance(container.llm, FakeLLM)
    return container.llm


def _plan(*steps: dict) -> str:
    return json.dumps({"summary": "plan", "steps": list(steps)})


def _delegate(role: str, task: str) -> dict:
    return {"tool": "agent.delegate", "args": {"role": role, "task": task}}


def _context(container: Container, depth: int = 0) -> ToolContext:
    return ToolContext(
        memory=container.memory,
        settings=container.settings,
        events=container.events,
        db=container.db,
        box=container.box,
        loop=container.agent,
        depth=depth,
    )


# --------------------------------------------------------------------- roster


def test_roster_has_one_orchestrator_and_ten_specialists() -> None:
    assert ROSTER[0].id == ORCHESTRATOR_ID
    assert len(SPECIALISTS) == 10
    assert len({role.id for role in ROSTER}) == len(ROSTER)


def test_only_the_orchestrator_can_delegate() -> None:
    assert ROSTER[0].can_delegate is True
    assert all(role.can_delegate is False for role in SPECIALISTS)


def test_handover_roles_are_present() -> None:
    required = {
        "engineer",
        "research",
        "security",
        "testing",
        "browser",
        "desktop",
        "creative",
        "memory",
        "critic",
    }
    assert required <= set(SPECIALIST_IDS)


@pytest.mark.parametrize("role", SPECIALISTS, ids=SPECIALIST_IDS)
def test_each_specialist_resolves_real_tools(container: Container, role) -> None:
    manifests = container.team.manifests_for(role)
    assert manifests, f"{role.id} resolved no available tools"
    # Specialists must never be able to widen their own reach.
    assert all(manifest.name != "agent.delegate" for manifest in manifests)


@pytest.mark.parametrize("role", SPECIALISTS, ids=SPECIALIST_IDS)
def test_each_specialist_has_an_honest_backend(container: Container, role) -> None:
    assert role.backend.strip(), f"{role.id} does not declare a backend"
    assert role.capability in {"full", "partial", "routing"}
    described = {item["id"]: item for item in container.team.describe()}
    assert described[role.id]["available_tools"]


# ------------------------------------------------------- individual role runs


@pytest.mark.parametrize("role", SPECIALISTS, ids=SPECIALIST_IDS)
async def test_each_specialist_completes_a_run(container: Container, role) -> None:
    _fake(container).responses = [_plan(), f"{role.name} reporting."]
    result = await container.agent.start("Report your status", role=role.id)
    assert result.status is RunStatus.COMPLETED
    assert result.role == role.id
    assert result.answer == f"{role.name} reporting."
    assert container.audit.verify().ok


async def test_specialist_uses_only_its_own_tools(container: Container) -> None:
    _fake(container).responses = [
        _plan({"tool": "memory.search", "args": {"query": "tea"}}),
        json.dumps({"done": True, "reason": "searched memory"}),
        "No stored memories about tea.",
    ]
    result = await container.agent.start("What do you remember?", role="memory")
    assert result.status is RunStatus.COMPLETED
    assert result.steps[0].tool == "memory.search"
    assert result.steps[0].ok is True


async def test_specialist_cannot_call_tool_outside_its_scope(container: Container) -> None:
    # notes.delete is a memory/writer tool, not a research tool.
    bad_plan = _plan({"tool": "notes.delete", "args": {"id": "abc"}})
    _fake(container).responses = [bad_plan, bad_plan, bad_plan]
    result = await container.agent.start("Delete that note", role="research")
    assert result.status is RunStatus.FAILED
    assert "outside this agent's scope" in (result.error or "")


async def test_specialist_cannot_delegate(container: Container) -> None:
    bad_plan = _plan(_delegate("memory", "Do the work"))
    _fake(container).responses = [bad_plan, bad_plan, bad_plan]
    result = await container.agent.start("Delegate this", role="research")
    assert result.status is RunStatus.FAILED
    assert "outside this agent's scope" in (result.error or "")


async def test_unknown_role_is_rejected(container: Container) -> None:
    with pytest.raises(RunError):
        await container.agent.start("Do something", role="not-a-role")


async def test_delegation_depth_limit_is_enforced(container: Container) -> None:
    with pytest.raises(RunError):
        await container.agent.start("Too deep", role="research", depth=5)


async def test_roster_tool_lists_the_whole_team(container: Container) -> None:
    _fake(container).responses = [
        _plan({"tool": "agent.roster", "args": {}}),
        json.dumps({"done": True, "reason": "roster listed"}),
        "The team is listed.",
    ]
    result = await container.agent.start("List the agent team")
    assert result.status is RunStatus.COMPLETED
    roster = result.steps[0].output
    assert len(roster) == 11
    assert {item["id"] for item in roster} >= {"research", "memory", "critic"}


# ------------------------------------------------------------- collaboration


async def test_orchestrator_delegates_to_a_specialist(container: Container) -> None:
    _fake(container).responses = [
        _plan(_delegate("research", "Summarise the local project layout.")),
        _plan(),
        "Specialist summary.",
        json.dumps({"done": True, "reason": "delegation completed"}),
        "Final combined answer.",
    ]
    result = await container.agent.start("Research the project")
    assert result.status is RunStatus.COMPLETED
    assert result.role == ORCHESTRATOR_ID

    step = result.steps[0]
    assert step.tool == "agent.delegate"
    assert step.ok is True

    sub = container.agent.get(step.output["run_id"])
    assert sub is not None
    assert sub.role == "research"
    assert sub.parent_run_id == result.run_id
    assert sub.answer == "Specialist summary."


async def test_multi_agent_collaboration_chains_two_specialists(container: Container) -> None:
    _fake(container).responses = [
        _plan(
            _delegate("research", "Gather the facts."),
            _delegate("writer", "Write the facts up."),
        ),
        _plan(),
        "Research result.",
        _plan(),
        "Written result.",
        json.dumps({"done": True, "reason": "both specialists reported"}),
        "Combined final answer.",
    ]
    result = await container.agent.start("Research and document")
    assert result.status is RunStatus.COMPLETED
    assert len(result.steps) == 2

    roles = []
    for step in result.steps:
        sub = container.agent.get(step.output["run_id"])
        assert sub is not None
        assert sub.parent_run_id == result.run_id
        roles.append(sub.role)
    assert roles == ["research", "writer"]

    audit = container.audit.tail(200)
    assert any(entry.tool == "agent.delegate" for entry in audit)
    assert container.audit.verify().ok


async def test_delegation_to_unknown_role_is_refused(container: Container) -> None:
    result = await delegate_tool(
        {"role": "wizard", "task": "Do magic"}, _context(container)
    )
    assert result.ok is False
    assert "unknown agent role" in (result.error or "")


async def test_orchestrator_cannot_delegate_to_itself(container: Container) -> None:
    result = await delegate_tool(
        {"role": ORCHESTRATOR_ID, "task": "Recurse forever"}, _context(container)
    )
    assert result.ok is False
    assert "cannot delegate to itself" in (result.error or "")


async def test_planner_rejects_an_out_of_roster_role(container: Container) -> None:
    # The schema enum is the first line of defence; the run fails before any tool call.
    bad = _plan(_delegate("wizard", "Do magic"))
    _fake(container).responses = [bad, bad, bad]
    result = await container.agent.start("Delegate to a wizard")
    assert result.status is RunStatus.FAILED
    assert "planning failed" in (result.error or "")


async def test_specialist_approval_pauses_the_delegation(container: Container) -> None:
    _fake(container).responses = [
        _plan(_delegate("memory", "Forget the memory with id missing-id")),
        _plan({"tool": "memory.forget", "args": {"id": "missing-id"}}),
        json.dumps({"done": True, "reason": "reported the pending approval"}),
        "The memory agent needs your approval before deleting anything.",
    ]
    result = await container.agent.start("Forget that memory")
    assert result.status is RunStatus.COMPLETED

    step = result.steps[0]
    assert step.ok is False
    assert "paused for approval" in (step.error or "")

    sub = container.agent.get(step.output["run_id"])
    assert sub is not None
    assert sub.status is RunStatus.AWAITING_APPROVAL
    assert sub.approval is not None
    assert sub.approval.tool == "memory.forget"


async def test_kill_switch_blocks_specialist_work(container: Container) -> None:
    container.kill_switch.engage("test stop")
    with pytest.raises(KillSwitchEngaged):
        await container.agent.start("Gather facts", role="research")
    container.kill_switch.release()


# ------------------------------------------------------------------ API layer


def test_agents_endpoint_exposes_the_roster(settings: Settings) -> None:
    app = create_app(settings, llm=FakeLLM([]), embeddings=None)
    client = TestClient(app)
    response = client.get("/api/v1/agents")
    assert response.status_code == 200
    body = response.json()
    assert body["orchestrator"] == ORCHESTRATOR_ID
    assert body["specialist_count"] == 10
    assert len(body["agents"]) == 11
    ids = {item["id"] for item in body["agents"]}
    assert "research" in ids
    assert all(item["available_tools"] for item in body["agents"])
