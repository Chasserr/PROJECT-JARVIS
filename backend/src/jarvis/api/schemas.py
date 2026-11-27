"""Request and response schemas for the HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..agent.models import RunResult
from ..memory.models import Memory
from ..tools.manifest import ToolManifest


class HealthResponse(BaseModel):
    status: str
    version: str
    provider: str
    model: str
    database: bool
    memory_count: int
    tool_count: int
    cloud_enabled: bool


class ToolInfo(BaseModel):
    name: str
    version: str
    description: str
    permission: str
    dangerous: bool
    tags: list[str]
    input_schema: dict[str, Any]

    @classmethod
    def from_manifest(cls, manifest: ToolManifest, permission: str) -> ToolInfo:
        return cls(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            permission=permission,
            dangerous=manifest.dangerous,
            tags=manifest.tags,
            input_schema=manifest.input_schema,
        )


class AgentInfo(BaseModel):
    id: str
    name: str
    description: str
    backend: str
    capability: str
    can_delegate: bool
    tools: list[str]
    available_tools: list[str]
    missing_tools: list[str]
    notes: str = ""


class AgentListResponse(BaseModel):
    orchestrator: str
    agents: list[AgentInfo]
    specialist_count: int


class MemoryListResponse(BaseModel):
    memories: list[Memory]
    count: int


class ChatMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=6000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)
    legacy_memory: str = Field(default="", max_length=10000)


class RunRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(default="default", max_length=100)
    context: str = Field(default="", max_length=8000)
    # Run the goal as one specialist instead of the orchestrator.
    role: str | None = Field(default=None, max_length=40)


class ApprovalDecision(BaseModel):
    approve: bool


class RunListResponse(BaseModel):
    runs: list[RunResult]


class AuditVerifyResponse(BaseModel):
    ok: bool
    checked: int
    first_bad_seq: int | None = None
    message: str
