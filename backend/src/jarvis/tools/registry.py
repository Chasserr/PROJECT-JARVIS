"""Tool registry: schema validation, permission gate, timeout, audit, events."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel

from ..config import Settings
from ..db import Database
from ..events import EventBus, EventType
from ..memory.store import MemoryStore
from ..security.audit import AuditLog
from ..security.crypto import SecretBox
from ..security.permissions import Decision, PermissionPolicy, PermissionTier
from .manifest import ToolManifest

_SECRET_HINTS = ("password", "token", "secret", "api_key", "apikey", "authorization")


class ToolError(RuntimeError):
    pass


class ToolValidationError(ToolError):
    pass


class ApprovalRequired(ToolError):
    def __init__(self, manifest: ToolManifest, args: dict[str, Any], reason: str) -> None:
        super().__init__(f"approval required for {manifest.name}: {reason}")
        self.manifest = manifest
        self.args = args
        self.reason = reason
        self.signature = approval_signature(manifest.name, args)


class ToolResult(BaseModel):
    ok: bool
    output: Any = None
    error: str | None = None
    duration_ms: int = 0


@dataclass
class ToolContext:
    memory: MemoryStore
    settings: Settings
    events: EventBus
    db: Database | None = None
    box: SecretBox | None = None
    actor: str = "local"
    run_id: str | None = None
    session_id: str = "default"


ToolReturn = ToolResult | dict[str, Any] | str
ToolFunc = Callable[[dict[str, Any], ToolContext], Awaitable[ToolReturn] | ToolReturn]


@dataclass
class Tool:
    manifest: ToolManifest
    func: ToolFunc


def approval_signature(tool: str, args: dict[str, Any]) -> str:
    material = f"{tool}:{json.dumps(args, sort_keys=True, default=str, separators=(',', ':'))}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if any(hint in key.lower() for hint in _SECRET_HINTS):
                result[key] = "[redacted]"
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class ToolRegistry:
    def __init__(
        self,
        *,
        policy: PermissionPolicy,
        audit: AuditLog,
        events: EventBus,
        settings: Settings,
    ) -> None:
        self._policy = policy
        self._audit = audit
        self._events = events
        self._settings = settings
        self._tools: dict[str, Tool] = {}

    def register(self, manifest: ToolManifest, func: ToolFunc) -> None:
        if manifest.name in self._tools:
            raise ToolError(f"tool already registered: {manifest.name}")
        self._tools[manifest.name] = Tool(manifest=manifest, func=func)

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool: {name}")
        return tool

    def manifests(self) -> list[ToolManifest]:
        return [self._tools[name].manifest for name in sorted(self._tools)]

    def specs(self) -> list[dict[str, Any]]:
        return [manifest.spec() for manifest in self.manifests()]

    def has(self, name: str) -> bool:
        return name in self._tools

    def effective_permission(self, manifest: ToolManifest) -> PermissionTier:
        return self._policy.effective(manifest)

    async def execute(
        self,
        name: str,
        args: dict[str, Any],
        context: ToolContext,
        *,
        approved: bool = False,
    ) -> ToolResult:
        tool = self.get(name)
        self._validate_args(tool.manifest, args)
        decision = self._policy.evaluate(tool.manifest)
        if decision is Decision.CONFIRM and not approved:
            self._audit.record(
                actor=context.actor,
                action="tool.approval_required",
                tool=name,
                permission=self._policy.effective(tool.manifest).value,
                outcome="pending",
                detail={"args": redact(args), "run_id": context.run_id},
            )
            await self._events.publish(
                EventType.APPROVAL_REQUESTED,
                {
                    "tool": name,
                    "args": redact(args),
                    "run_id": context.run_id,
                    "signature": approval_signature(name, args),
                },
            )
            raise ApprovalRequired(tool.manifest, args, "tool permission tier is confirm")
        if decision is Decision.DENY:
            return ToolResult(ok=False, error=f"tool denied by policy: {name}")

        timeout = tool.manifest.timeout_s or self._settings.tool_timeout_s
        started = time.perf_counter()

        async def invoke() -> ToolReturn:
            value = tool.func(args, context)
            if inspect.isawaitable(value):
                return await value
            return value

        try:
            raw = await asyncio.wait_for(invoke(), timeout=timeout)
            if isinstance(raw, ToolResult):
                result = raw
            elif isinstance(raw, dict | list):
                result = ToolResult(ok=True, output=raw)
            else:
                result = ToolResult(ok=True, output=str(raw))
        except TimeoutError:
            result = ToolResult(ok=False, error=f"tool timed out after {timeout:.0f}s")
        except Exception as exc:
            result = ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        result.duration_ms = int((time.perf_counter() - started) * 1000)

        self._audit.record(
            actor=context.actor,
            action="tool.called",
            tool=name,
            permission=self._policy.effective(tool.manifest).value,
            outcome="ok" if result.ok else "error",
            detail={
                "args": redact(args),
                "duration_ms": result.duration_ms,
                "error": result.error,
                "run_id": context.run_id,
            },
        )
        await self._events.publish(
            EventType.TOOL_CALLED,
            {
                "tool": name,
                "ok": result.ok,
                "duration_ms": result.duration_ms,
                "run_id": context.run_id,
            },
        )
        return result

    def _validate_args(self, manifest: ToolManifest, args: dict[str, Any]) -> None:
        if not isinstance(args, dict):
            raise ToolValidationError("tool arguments must be an object")
        errors = sorted(
            Draft202012Validator(manifest.input_schema).iter_errors(args),
            key=lambda error: list(error.path),
        )
        if errors:
            first = errors[0]
            path = ".".join(str(part) for part in first.path) or "<root>"
            raise ToolValidationError(f"invalid arguments at {path}: {first.message}")


__all__ = [
    "ApprovalRequired",
    "PermissionTier",
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolManifest",
    "ToolRegistry",
    "ToolResult",
    "ToolValidationError",
    "approval_signature",
    "redact",
]
