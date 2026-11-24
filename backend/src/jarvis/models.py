from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class PermissionTier(StrEnum):
    READ_ONLY = "read_only"
    CONFIRM_BEFORE_ACT = "confirm_before_act"
    AUTONOMOUS = "autonomous"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ToolCall:
    skill_id: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlanStep:
    description: str
    tool: ToolCall | None = None


@dataclass(slots=True)
class AgentTask:
    request: str
    id: str = field(default_factory=lambda: uuid4().hex)
    status: TaskStatus = TaskStatus.PENDING
    steps: list[PlanStep] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
