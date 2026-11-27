"""Agent data models shared by the loop, API, and CLI."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class Plan(BaseModel):
    summary: str = ""
    steps: list[PlanStep] = Field(default_factory=list)


class StepRecord(BaseModel):
    index: int
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    output: Any = None
    error: str | None = None
    duration_ms: int = 0


class ApprovalRequest(BaseModel):
    run_id: str
    step_index: int
    tool: str
    args: dict[str, Any]
    permission: str
    signature: str


class RunStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunResult(BaseModel):
    run_id: str
    status: RunStatus
    goal: str
    answer: str | None = None
    plan: Plan | None = None
    steps: list[StepRecord] = Field(default_factory=list)
    error: str | None = None
    approval: ApprovalRequest | None = None
    attempt: int = 0
    role: str | None = None
    parent_run_id: str | None = None
