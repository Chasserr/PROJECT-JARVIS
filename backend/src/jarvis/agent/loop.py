from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from jarvis.agent.policy import PolicyEngine
from jarvis.events import Event, EventBus
from jarvis.memory.store import MemoryStore
from jarvis.models import AgentTask, PlanStep, TaskStatus, ToolCall
from jarvis.skills.manifest import validate_skill_arguments


class Planner(Protocol):
    async def plan(self, request: str, memories: list[dict[str, Any]]) -> list[PlanStep]: ...


class Critic(Protocol):
    async def verify(self, request: str, results: list[dict[str, Any]]) -> tuple[bool, str]: ...


ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class Agent:
    """Bounded agent loop with in-process, one-action approval resumption."""

    def __init__(self, planner: Planner, critic: Critic, tools: dict[str, ToolHandler],
                 policy: PolicyEngine, memory: MemoryStore, events: EventBus,
                 *, max_steps: int = 8, max_retries_per_step: int = 1,
                 tool_schemas: dict[str, set[str]] | None = None,
                 tool_argument_types: dict[str, dict[str, str]] | None = None,
                 planner_timeout_seconds: float = 75.0,
                 tool_timeout_seconds: float = 90.0,
                 critic_timeout_seconds: float = 45.0,
                 max_concurrent_tools: int = 2) -> None:
        self.planner, self.critic, self.tools = planner, critic, tools
        self.policy, self.memory, self.events = policy, memory, events
        self.max_steps = max_steps
        self.tool_schemas = tool_schemas or {}
        self.tool_argument_types = tool_argument_types or {}
        self.max_retries_per_step = 0  # Never replay a tool: a timeout may occur after its side effect.
        self.planner_timeout_seconds = max(0.1, planner_timeout_seconds)
        self.tool_timeout_seconds = max(0.1, tool_timeout_seconds)
        self.critic_timeout_seconds = max(0.1, critic_timeout_seconds)
        self._tool_semaphore = asyncio.Semaphore(max(1, min(max_concurrent_tools, 4)))
        self._cancel_requested: set[str] = set()
        self._tasks: dict[str, AgentTask] = {}
        self._pending: dict[str, int] = {}
        self._restore_tasks()

    @staticmethod
    def _serialize(task: AgentTask) -> dict[str, Any]:
        return {
            "id": task.id, "request": task.request, "status": task.status.value,
            "steps": [{"description": step.description,
                       "tool": ({"skill_id": step.tool.skill_id,
                                 "arguments": step.tool.arguments} if step.tool else None)}
                      for step in task.steps],
            "results": task.results, "error": task.error,
        }

    def _persist(self, task: AgentTask) -> None:
        self.memory.save_task(self._serialize(task))

    def _restore_tasks(self) -> None:
        for record in self.memory.list_tasks(limit=500):
            steps = []
            for item in record.get("steps", []):
                tool = item.get("tool")
                steps.append(PlanStep(
                    description=item.get("description", ""),
                    tool=ToolCall(tool["skill_id"], tool.get("arguments", {})) if tool else None,
                ))
            task = AgentTask(
                request=record["request"], id=record["id"],
                status=TaskStatus(record["status"]), steps=steps,
                results=record.get("results", []), error=record.get("error"),
            )
            if task.status in {TaskStatus.RUNNING, TaskStatus.AWAITING_APPROVAL, TaskStatus.PENDING}:
                task.status = TaskStatus.FAILED
                task.error = (
                    "JARVIS restarted while this task was in progress. "
                    "Its last action may have completed; review the task before retrying."
                )
                self.memory.audit(
                    actor="system", action="task.recovery", resource=task.id,
                    decision="interrupted", reason=task.error, correlation_id=task.id,
                )
                self._persist(task)
            self._tasks[task.id] = task

    async def cancel_task(self, task_id: str) -> AgentTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise LookupError("Task not found.")
        if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            return task
        self._cancel_requested.add(task_id)
        self._pending.pop(task_id, None)
        if task.status is TaskStatus.AWAITING_APPROVAL:
            task.status = TaskStatus.CANCELLED
            task.error = "Task cancelled by user before approval; the protected action was not executed."
            self._persist(task)
            self.memory.audit(actor="user", action="task.cancel", resource=task.id,
                              decision="cancelled", reason=task.error, correlation_id=task.id)
            await self.events.publish(Event("agent.cancelled", {"task_id": task.id}, task.id))
        else:
            await self.events.publish(Event("agent.cancel_requested", {"task_id": task.id}, task.id))
        return task

    def _is_cancel_requested(self, task: AgentTask) -> bool:
        return task.id in self._cancel_requested

    def get_task(self, task_id: str) -> AgentTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 100) -> list[AgentTask]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        return list(reversed(list(self._tasks.values())))[0:limit]

    async def run(self, task: AgentTask) -> AgentTask:
        if task.id in self._tasks:
            raise ValueError("Task ID is already active.")
        self._tasks[task.id] = task
        task.status = TaskStatus.RUNNING
        self._persist(task)
        await self.events.publish(Event("agent.started", {"task_id": task.id}, task.id))
        try:
            task.steps = await asyncio.wait_for(
                self.planner.plan(task.request, self.memory.list_memories()),
                timeout=self.planner_timeout_seconds,
            )
            if self._is_cancel_requested(task):
                return self._mark_cancelled(task)
            if not task.steps or len(task.steps) > self.max_steps:
                raise ValueError(f"Planner must return between 1 and {self.max_steps} steps.")
            self._persist(task)
            return await self._continue(task, 0)
        except Exception as exc:  # noqa: BLE001
            return await self._fail(task, exc)

    async def approve(self, task_id: str, *, approved: bool) -> AgentTask:
        task = self._tasks.get(task_id)
        index = self._pending.get(task_id)
        if task is None or index is None or task.status is not TaskStatus.AWAITING_APPROVAL:
            raise LookupError("No pending approval exists for this task.")
        self._pending.pop(task_id, None)
        step = task.steps[index]
        tool = step.tool
        if tool is None:
            raise RuntimeError("Pending approval step has no tool call.")
        if not approved:
            task.status = TaskStatus.CANCELLED
            task.error = "User declined the requested action."
            self._persist(task)
            self.memory.audit(actor="user", action="tool.approval", resource=tool.skill_id,
                              decision="deny", reason=task.error, correlation_id=task.id)
            await self.events.publish(Event("agent.approval_denied",
                {"task_id": task.id, "skill_id": tool.skill_id}, task.id))
            return task
        self.memory.audit(actor="user", action="tool.approval", resource=tool.skill_id,
                          decision="allow", reason="User explicitly approved this action.",
                          correlation_id=task.id)
        task.status = TaskStatus.RUNNING
        self._persist(task)
        return await self._continue(task, index, approved_index=index)

    async def _continue(self, task: AgentTask, start: int, *, approved_index: int | None = None) -> AgentTask:
        try:
            for index in range(start, len(task.steps)):
                if self._is_cancel_requested(task):
                    return self._mark_cancelled(task)
                step = task.steps[index]
                tool = step.tool
                if tool is None:
                    task.results.append({"step": index, "description": step.description, "ok": True})
                    continue
                expected_args = self.tool_schemas.get(tool.skill_id)
                if expected_args is None:
                    raise PermissionError(f"Skill '{tool.skill_id}' is not in the executor registry.")
                if set(tool.arguments) != expected_args:
                    raise ValueError(f"Invalid arguments for '{tool.skill_id}'. Expected: {sorted(expected_args)}")
                argument_types = self.tool_argument_types.get(tool.skill_id)
                if argument_types is not None:
                    validate_skill_arguments(tool.skill_id, tool.arguments, argument_types)
                decision = self.policy.evaluate(tool)
                already_approved = index == approved_index
                self.memory.audit(actor="agent", action="tool.execute", resource=tool.skill_id,
                                  decision=("approved" if already_approved else
                                            "allow" if decision.allowed else "deny"),
                                  reason="One-time approval" if already_approved else decision.reason,
                                  correlation_id=task.id)
                if decision.requires_approval and not already_approved:
                    task.status = TaskStatus.AWAITING_APPROVAL
                    task.error = decision.reason
                    self._pending[task.id] = index
                    self._persist(task)
                    await self.events.publish(Event("agent.approval_required",
                        {"task_id": task.id, "skill_id": tool.skill_id,
                         "description": step.description}, task.id))
                    return task
                if not decision.allowed and not (decision.requires_approval and already_approved):
                    raise PermissionError(decision.reason)
                handler = self.tools.get(tool.skill_id)
                if handler is None:
                    raise LookupError(f"No handler registered for skill '{tool.skill_id}'.")
                last_error: Exception | None = None
                for attempt in range(self.max_retries_per_step + 1):
                    try:
                        async with self._tool_semaphore:
                            result = await asyncio.wait_for(
                                handler(tool.arguments), timeout=self.tool_timeout_seconds
                            )
                        last_error = None
                        break
                    except (ValueError, PermissionError, LookupError):
                        raise
                    except Exception as exc:
                        last_error = exc
                        if attempt >= self.max_retries_per_step:
                            raise
                if last_error is not None:
                    raise last_error
                task.results.append({"step": index, "skill_id": tool.skill_id,
                                     "result": result, "attempts": attempt + 1})
                self._persist(task)
                await self.events.publish(Event("agent.step.completed",
                    {"task_id": task.id, "step": index}, task.id))
                if self._is_cancel_requested(task):
                    return self._mark_cancelled(task)
            if self._is_cancel_requested(task):
                return self._mark_cancelled(task)
            verified, note = await asyncio.wait_for(
                self.critic.verify(task.request, task.results),
                timeout=self.critic_timeout_seconds,
            )
            if self._is_cancel_requested(task):
                return self._mark_cancelled(task)
            if not verified:
                raise RuntimeError(f"Critic could not verify completion: {note}")
            task.status, task.error = TaskStatus.COMPLETED, None
            self._persist(task)
            self.memory.audit(actor="agent", action="task.finish", resource=task.id,
                              decision=task.status.value, reason=note, correlation_id=task.id)
            await self.events.publish(Event("agent.finished",
                {"task_id": task.id, "status": task.status.value}, task.id))
        except Exception as exc:  # noqa: BLE001
            return await self._fail(task, exc)
        return task

    def _mark_cancelled(self, task: AgentTask) -> AgentTask:
        task.status = TaskStatus.CANCELLED
        task.error = "Task cancelled by user. Any action already in progress was allowed to finish; no later steps were started."
        self._persist(task)
        self.memory.audit(actor="user", action="task.cancel", resource=task.id,
                          decision="cancelled", reason=task.error, correlation_id=task.id)
        return task

    async def _fail(self, task: AgentTask, exc: Exception) -> AgentTask:
        task.status, task.error = TaskStatus.FAILED, (str(exc) or type(exc).__name__)[:1_000]
        self._persist(task)
        self.memory.audit(actor="agent", action="task.fail", resource=task.id,
                          decision="failed", reason=type(exc).__name__, correlation_id=task.id)
        await self.events.publish(Event("agent.failed",
            {"task_id": task.id, "error": task.error}, task.id))
        return task
