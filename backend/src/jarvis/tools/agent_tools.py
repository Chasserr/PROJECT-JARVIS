"""Tools that expose the specialist team to the orchestrator.

``agent.delegate`` does not run a second loop. It calls back into the same
``AgentLoop`` with a role scope, so the delegated run is a normal durable run
with its own audit trail, permission checks, approval pause and kill-switch
handling.
"""

from __future__ import annotations

from typing import Any

from ..security.permissions import PermissionTier
from .manifest import ToolManifest
from .registry import ToolContext, ToolRegistry, ToolResult


def _loop_and_team(context: ToolContext) -> tuple[Any, Any]:
    loop = context.loop
    team = getattr(loop, "team", None) if loop is not None else None
    return loop, team


def _roster(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _loop, team = _loop_and_team(context)
    if team is None:
        return ToolResult(ok=False, error="no specialist agent team is configured")
    return ToolResult(ok=True, output=team.describe())


async def _delegate(args: dict[str, Any], context: ToolContext) -> ToolResult:
    loop, team = _loop_and_team(context)
    if loop is None or team is None:
        return ToolResult(ok=False, error="no specialist agent team is configured")

    role_id = str(args["role"]).strip()
    task = str(args["task"]).strip()
    if not task:
        return ToolResult(ok=False, error="delegation task must not be empty")

    try:
        role = team.get(role_id)
    except KeyError:
        known = ", ".join(item.id for item in team.specialists())
        return ToolResult(ok=False, error=f"unknown agent role '{role_id}'. Known: {known}")

    if role.id == team.orchestrator_id:
        return ToolResult(ok=False, error="the orchestrator cannot delegate to itself")

    if not team.manifests_for(role):
        return ToolResult(
            ok=False,
            error=f"agent '{role.id}' has no available tools on this machine",
        )

    if context.depth + 1 > team.max_depth:
        return ToolResult(
            ok=False,
            error=f"delegation depth limit reached ({team.max_depth})",
        )

    try:
        result = await loop.start(
            task,
            role=role.id,
            depth=context.depth + 1,
            parent_run_id=context.run_id,
            session_id=context.session_id,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the orchestrator, never hidden
        return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    payload: dict[str, Any] = {
        "run_id": result.run_id,
        "role": role.id,
        "role_name": role.name,
        "status": result.status.value,
        "answer": result.answer,
        "steps": [
            {
                "tool": record.tool,
                "ok": record.ok,
                "error": record.error,
                "output": record.output,
            }
            for record in result.steps
        ],
    }

    if result.status.value == "awaiting_approval":
        approval = result.approval
        return ToolResult(
            ok=False,
            output=payload,
            error=(
                f"agent '{role.id}' paused for approval of "
                f"'{approval.tool if approval else 'a step'}' (run {result.run_id})"
            ),
        )

    ok = result.status.value == "completed"
    return ToolResult(
        ok=ok,
        output=payload,
        error=None if ok else (result.error or f"agent '{role.id}' finished as {result.status.value}"),
    )


def register_agent_tools(registry: ToolRegistry) -> None:
    """Register the roster and delegation tools. Safe to call once per registry."""
    registry.register(
        ToolManifest(
            name="agent.roster",
            description=(
                "List the specialist agent team, each role's purpose, and the tools "
                "that role can actually use on this machine."
            ),
            permission=PermissionTier.READ_ONLY,
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            tags=["agents", "team"],
        ),
        _roster,
    )
    registry.register(
        ToolManifest(
            name="agent.delegate",
            description=(
                "Delegate a self-contained sub-task to one specialist agent and return "
                "its result. The specialist runs with its own restricted tool set and is "
                "still bound by audit, permissions and approvals."
            ),
            permission=PermissionTier.AUTONOMOUS,
            input_schema={
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": [
                            "engineer",
                            "research",
                            "security",
                            "testing",
                            "browser",
                            "desktop",
                            "creative",
                            "memory",
                            "critic",
                            "writer",
                        ],
                        "description": "Specialist role id to delegate to.",
                    },
                    "task": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 4000,
                        "description": "Self-contained task description for the specialist.",
                    },
                },
                "required": ["role", "task"],
                "additionalProperties": False,
            },
            tags=["agents", "delegation"],
        ),
        _delegate,
    )


__all__ = ["register_agent_tools"]
