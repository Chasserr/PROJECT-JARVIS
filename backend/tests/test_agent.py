from __future__ import annotations

import json

import pytest

from jarvis.agent.models import RunStatus
from jarvis.container import Container
from jarvis.memory.models import MemoryCreate
from jarvis.security.kill_switch import KillSwitchEngaged

from .conftest import FakeLLM


def _fake(container: Container) -> FakeLLM:
    assert isinstance(container.llm, FakeLLM)
    return container.llm


def _plan(*steps: dict) -> str:
    return json.dumps({"summary": "plan", "steps": list(steps)})


async def test_zero_step_goal_answers_directly(container: Container) -> None:
    _fake(container).responses = [_plan(), "Hello, I am JARVIS."]
    result = await container.agent.start("Say hello")
    assert result.status is RunStatus.COMPLETED
    assert result.answer == "Hello, I am JARVIS."
    assert result.steps == []
    assert container.audit.verify().ok


async def test_tool_step_completes(container: Container) -> None:
    _fake(container).responses = [
        _plan({"tool": "time.now", "args": {"timezone": "UTC"}}),
        json.dumps({"done": True, "reason": "time retrieved"}),
        "The clock is available.",
    ]
    result = await container.agent.start("What time is it?")
    assert result.status is RunStatus.COMPLETED
    assert len(result.steps) == 1
    assert result.steps[0].tool == "time.now"
    assert result.steps[0].ok is True
    assert result.answer == "The clock is available."


async def test_confirm_tool_pauses_and_resumes(container: Container) -> None:
    _fake(container).responses = [_plan({"tool": "memory.forget", "args": {"id": "missing-id"}})]
    result = await container.agent.start("Forget that memory")
    assert result.status is RunStatus.AWAITING_APPROVAL
    assert result.approval is not None
    assert result.approval.tool == "memory.forget"

    _fake(container).responses = [
        json.dumps({"done": True, "reason": "forget attempted"}),
        "I removed it.",
    ]
    resumed = await container.agent.resume(result.run_id, approved=True)
    assert resumed.status is RunStatus.COMPLETED
    assert resumed.answer == "I removed it."
    assert resumed.approval is None


async def test_denied_approval_fails(container: Container) -> None:
    _fake(container).responses = [_plan({"tool": "memory.forget", "args": {"id": "missing-id"}})]
    result = await container.agent.start("Forget that memory")
    denied = await container.agent.resume(result.run_id, approved=False)
    assert denied.status is RunStatus.FAILED
    assert "denied" in (denied.error or "")


async def test_failed_step_triggers_replan(container: Container) -> None:
    _fake(container).responses = [
        _plan({"tool": "time.now", "args": {"timezone": "Not/AZone"}}),
        json.dumps({"done": False, "reason": "the timezone was invalid"}),
        _plan(),
        "I could not resolve that timezone.",
    ]
    result = await container.agent.start("What time is it in Not/AZone?")
    assert result.status is RunStatus.COMPLETED
    assert result.attempt == 1
    assert result.answer == "I could not resolve that timezone."


async def test_replan_budget_exhaustion(container: Container) -> None:
    container.settings.max_replans = 0
    _fake(container).responses = [
        _plan({"tool": "time.now", "args": {"timezone": "Not/AZone"}}),
        json.dumps({"done": False, "reason": "invalid timezone"}),
    ]
    result = await container.agent.start("What time is it in Not/AZone?")
    assert result.status is RunStatus.FAILED
    assert "replan budget" in (result.error or "")


async def test_memory_context_is_injected_into_prompts(container: Container) -> None:
    await container.memory.add(MemoryCreate(content="My favourite tea is jasmine"))
    _fake(container).responses = [_plan(), "You like jasmine tea."]
    result = await container.agent.start("What is my favourite tea?")
    assert result.status is RunStatus.COMPLETED
    planner_prompt = _fake(container).calls[0][1].content
    assert "jasmine" in planner_prompt.lower()
    answer_prompt = _fake(container).calls[-1][1].content
    assert "jasmine" in answer_prompt.lower()


async def test_kill_switch_blocks_new_work(container: Container) -> None:
    container.kill_switch.engage("test stop")
    with pytest.raises(KillSwitchEngaged):
        await container.agent.start("Say hello")
    container.kill_switch.release()
    _fake(container).responses = [_plan(), "Back online."]
    result = await container.agent.start("Say hello")
    assert result.status is RunStatus.COMPLETED
    assert result.answer == "Back online."
