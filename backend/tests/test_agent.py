import asyncio

from jarvis.agent.loop import Agent
from jarvis.agent.policy import PolicyEngine
from jarvis.events import EventBus
from jarvis.memory.store import MemoryStore
from jarvis.models import AgentTask, PermissionTier, PlanStep, TaskStatus, ToolCall


class FakePlanner:
    def __init__(self, steps):
        self.steps = steps

    async def plan(self, request, memories):
        return self.steps


class FakeCritic:
    async def verify(self, request, results):
        return True, "verified"


async def test_agent_executes_allowed_tool_and_verifies(tmp_path):
    async def read_note(args):
        return {"note": "safe"}

    agent = Agent(
        FakePlanner([PlanStep("Read a note", ToolCall("notes.read"))]),
        FakeCritic(),
        {"notes.read": read_note},
        PolicyEngine({"notes.read": PermissionTier.READ_ONLY}),
        MemoryStore(tmp_path / "memory.db"),
        EventBus(),
        tool_schemas={"notes.read": set()},
    )
    task = await agent.run(AgentTask("Read my note"))
    assert task.status is TaskStatus.COMPLETED
    assert task.results[0]["result"]["note"] == "safe"


async def test_agent_pauses_for_confirmation(tmp_path):
    async def close_app(args):
        return {"closed": True}

    agent = Agent(
        FakePlanner([PlanStep("Close an app", ToolCall("browser.click", {"text": "Delete account"}))]),
        FakeCritic(),
        {"browser.click": close_app},
        PolicyEngine({"browser.click": PermissionTier.CONFIRM_BEFORE_ACT}),
        MemoryStore(tmp_path / "memory.db"),
        EventBus(),
        tool_schemas={"browser.click": {"text"}},
    )
    task = await agent.run(AgentTask("Close the app"))
    assert task.status is TaskStatus.AWAITING_APPROVAL
    assert task.results == []



async def test_approval_resumes_same_task_and_executes_once(tmp_path):
    calls = []

    async def render(args):
        calls.append(args["text"])
        return {"rendered": args["text"]}

    agent = Agent(
        FakePlanner([PlanStep("Render composition", ToolCall("browser.click", {"text": "Confirm payment"}))]),
        FakeCritic(),
        {"browser.click": render},
        PolicyEngine({"browser.click": PermissionTier.CONFIRM_BEFORE_ACT}),
        MemoryStore(tmp_path / "memory.db"),
        EventBus(),
        tool_schemas={"browser.click": {"text"}},
    )
    task = await agent.run(AgentTask("Render demo"))
    assert task.status is TaskStatus.AWAITING_APPROVAL
    assert calls == []

    resumed = await agent.approve(task.id, approved=True)
    assert resumed is task
    assert task.status is TaskStatus.COMPLETED
    assert calls == ["Confirm payment"]
    assert task.results[0]["result"]["rendered"] == "Confirm payment"


async def test_declined_approval_never_executes_tool(tmp_path):
    calls = []

    async def destructive(args):
        calls.append(True)
        return {"done": True}

    agent = Agent(
        FakePlanner([PlanStep("Do action", ToolCall("browser.click", {"text": "Send message"}))]),
        FakeCritic(),
        {"browser.click": destructive},
        PolicyEngine({"browser.click": PermissionTier.CONFIRM_BEFORE_ACT}),
        MemoryStore(tmp_path / "memory.db"),
        EventBus(),
        tool_schemas={"browser.click": {"text"}},
    )
    task = await agent.run(AgentTask("Do action"))
    assert task.status is TaskStatus.AWAITING_APPROVAL
    declined = await agent.approve(task.id, approved=False)
    assert declined.status is TaskStatus.CANCELLED
    assert calls == []


async def test_unknown_skill_and_argument_injection_are_rejected(tmp_path):
    async def safe(args):
        return {"ok": True}

    agent = Agent(
        FakePlanner([PlanStep("Unexpected", ToolCall("notes.read", {"path": "C:/"}))]),
        FakeCritic(),
        {"notes.read": safe},
        PolicyEngine({"notes.read": PermissionTier.READ_ONLY}),
        MemoryStore(tmp_path / "memory.db"),
        EventBus(),
        tool_schemas={"notes.read": {"note_id"}},
    )
    task = await agent.run(AgentTask("Read note"))
    assert task.status is TaskStatus.FAILED
    assert "Invalid arguments" in task.error


async def test_pending_approval_is_safely_recovered_after_restart(tmp_path):
    memory = MemoryStore(tmp_path / "memory.db")

    async def protected_action(args):
        return {"executed": True}

    kwargs = {
        "planner": FakePlanner([PlanStep("Protected action", ToolCall("browser.click", {"text": "Authorize transfer"}))]),
        "critic": FakeCritic(),
        "tools": {"browser.click": protected_action},
        "policy": PolicyEngine({"browser.click": PermissionTier.CONFIRM_BEFORE_ACT}),
        "memory": memory,
        "events": EventBus(),
        "tool_schemas": {"browser.click": {"text"}},
    }
    first_agent = Agent(**kwargs)
    pending = await first_agent.run(AgentTask("Run protected action"))
    assert pending.status is TaskStatus.AWAITING_APPROVAL

    restarted_agent = Agent(**kwargs)
    recovered = restarted_agent.get_task(pending.id)
    assert recovered is not None
    assert recovered.status is TaskStatus.FAILED
    assert "restarted" in recovered.error
    assert recovered.results == []


async def test_cancel_waiting_approval_prevents_protected_action(tmp_path):
    calls = []

    async def protected(args):
        calls.append(True)
        return {"done": True}

    agent = Agent(
        FakePlanner([PlanStep("Protected", ToolCall("browser.click", {"text": "Confirm"}))]),
        FakeCritic(), {"browser.click": protected},
        PolicyEngine({"browser.click": PermissionTier.CONFIRM_BEFORE_ACT}),
        MemoryStore(tmp_path / "memory.db"), EventBus(),
        tool_schemas={"browser.click": {"text"}},
    )
    task = await agent.run(AgentTask("Do protected action"))
    assert task.status is TaskStatus.AWAITING_APPROVAL
    cancelled = await agent.cancel_task(task.id)
    assert cancelled.status is TaskStatus.CANCELLED
    assert "before approval" in cancelled.error
    assert calls == []


async def test_cancel_running_task_waits_for_current_action_then_stops_next_step(tmp_path):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def slow_action(args):
        calls.append("first")
        entered.set()
        await release.wait()
        return {"finished": True}

    async def next_action(args):
        calls.append("second")
        return {"finished": True}

    steps = [
        PlanStep("First", ToolCall("slow.action", {})),
        PlanStep("Second", ToolCall("next.action", {})),
    ]
    agent = Agent(
        FakePlanner(steps), FakeCritic(),
        {"slow.action": slow_action, "next.action": next_action},
        PolicyEngine({"slow.action": PermissionTier.AUTONOMOUS,
                      "next.action": PermissionTier.AUTONOMOUS}),
        MemoryStore(tmp_path / "memory.db"), EventBus(),
        tool_schemas={"slow.action": set(), "next.action": set()},
    )
    running = asyncio.create_task(agent.run(AgentTask("Run two actions")))
    await entered.wait()
    task_id = next(iter(agent._tasks))
    await agent.cancel_task(task_id)
    release.set()
    result = await running
    assert result.status is TaskStatus.CANCELLED
    assert calls == ["first"]
    assert len(result.results) == 1


async def test_agent_rejects_wrong_argument_types_before_handler_execution(tmp_path):
    calls = []

    async def handler(args):
        calls.append(args)
        return {"ok": True}

    agent = Agent(
        FakePlanner([PlanStep("List processes", ToolCall("system.processes", {"limit": "all"}))]),
        FakeCritic(),
        {"system.processes": handler},
        PolicyEngine({"system.processes": PermissionTier.READ_ONLY}),
        MemoryStore(tmp_path / "memory.db"),
        EventBus(),
        tool_schemas={"system.processes": {"limit"}},
        tool_argument_types={"system.processes": {"limit": "integer"}},
    )

    task = await agent.run(AgentTask("List processes"))

    assert task.status is TaskStatus.FAILED
    assert "expected integer" in task.error
    assert calls == []


async def test_tool_timeout_fails_task_without_replaying_side_effect(tmp_path):
    calls = []

    async def slow_side_effect(args):
        calls.append("started")
        await asyncio.sleep(1)
        return {"done": True}

    agent = Agent(
        FakePlanner([PlanStep("Slow action", ToolCall("slow.action", {}))]),
        FakeCritic(), {"slow.action": slow_side_effect},
        PolicyEngine({"slow.action": PermissionTier.AUTONOMOUS}),
        MemoryStore(tmp_path / "memory.db"), EventBus(),
        tool_schemas={"slow.action": set()}, tool_timeout_seconds=0.1,
        max_retries_per_step=2,
    )
    task = await agent.run(AgentTask("Run slow action"))
    assert task.status is TaskStatus.FAILED
    assert "TimeoutError" in task.error
    assert calls == ["started"]


async def test_planner_timeout_is_bounded(tmp_path):
    class SlowPlanner:
        async def plan(self, request, memories):
            await asyncio.sleep(1)
            return [PlanStep("No-op", None)]

    agent = Agent(
        SlowPlanner(), FakeCritic(), {}, PolicyEngine({}),
        MemoryStore(tmp_path / "memory.db"), EventBus(),
        planner_timeout_seconds=0.1,
    )
    task = await agent.run(AgentTask("Wait forever"))
    assert task.status is TaskStatus.FAILED
    assert "TimeoutError" in task.error
