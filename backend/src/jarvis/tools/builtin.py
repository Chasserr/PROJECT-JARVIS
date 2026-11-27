"""Starter tools for Phase 1. Each is a real implementation, not a stub."""

from __future__ import annotations

import os
import platform
import sys
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..events import EventBus, EventType
from ..memory.models import MemoryCreate, MemoryKind
from ..security.audit import AuditLog
from ..security.permissions import PermissionPolicy, PermissionTier
from .manifest import ToolManifest
from .registry import ToolContext, ToolRegistry, ToolResult


def _now(args: dict[str, Any], context: ToolContext) -> ToolResult:
    timezone = args.get("timezone") or "UTC"
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {timezone}") from exc
    now = datetime.now(zone)
    return ToolResult(
        ok=True,
        output={
            "iso": now.isoformat(),
            "timezone": timezone,
            "epoch": now.timestamp(),
        },
    )


async def _memory_save(args: dict[str, Any], context: ToolContext) -> ToolResult:
    data = MemoryCreate(
        content=args["content"],
        kind=MemoryKind(args.get("kind", "fact")),
        tags=args.get("tags", []),
    )
    memory = await context.memory.add(data, source=context.actor)
    await context_events(context).publish(
        EventType.MEMORY_CREATED, {"id": memory.id, "kind": memory.kind}
    )
    return ToolResult(ok=True, output=memory.model_dump())


async def _memory_search(args: dict[str, Any], context: ToolContext) -> ToolResult:
    results = await context.memory.search(args["query"], args.get("limit", 5))
    return ToolResult(ok=True, output=[memory.model_dump() for memory in results])


def _memory_list(args: dict[str, Any], context: ToolContext) -> ToolResult:
    results = context.memory.list(args.get("limit", 20))
    return ToolResult(ok=True, output=[memory.model_dump() for memory in results])


def _memory_forget(args: dict[str, Any], context: ToolContext) -> ToolResult:
    deleted = context.memory.delete(args["id"], hard=args.get("hard", False))
    return ToolResult(ok=True, output={"deleted": deleted, "id": args["id"]})


def _system_info(args: dict[str, Any], context: ToolContext) -> ToolResult:
    return ToolResult(
        ok=True,
        output={
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cwd": os.getcwd(),
            "data_dir": str(context.settings.data_dir),
            "environment": context.settings.environment,
        },
    )


def _system_metrics(args: dict[str, Any], context: ToolContext) -> ToolResult:
    """Return real, read-only host metrics using Windows APIs and stdlib."""
    import ctypes
    import shutil
    import time

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    memory = MemoryStatus()
    memory.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise OSError("Windows could not read physical memory status.")
    disk = shutil.disk_usage(os.environ.get("SystemDrive", "C:") + os.sep)
    cpu_percent = None
    if os.name == "nt":
        class FileTime(ctypes.Structure):
            _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]
        def ticks(value):
            return (value.high << 32) | value.low
        idle1, kernel1, user1 = FileTime(), FileTime(), FileTime()
        if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle1), ctypes.byref(kernel1), ctypes.byref(user1)):
            time.sleep(0.25)
            idle2, kernel2, user2 = FileTime(), FileTime(), FileTime()
            if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle2), ctypes.byref(kernel2), ctypes.byref(user2)):
                idle_delta = ticks(idle2) - ticks(idle1)
                total_delta = (ticks(kernel2) - ticks(kernel1)) + (ticks(user2) - ticks(user1))
                if total_delta > 0:
                    cpu_percent = round(max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta))), 1)
    total = int(memory.ullTotalPhys)
    available = int(memory.ullAvailPhys)
    return ToolResult(ok=True, output={
        "cpu": {"usage_percent": cpu_percent, "logical_processors": os.cpu_count()},
        "memory": {"total_bytes": total, "available_bytes": available,
                   "used_bytes": total - available, "used_percent": round((total - available) / total * 100, 1) if total else None},
        "system_disk": {"total_bytes": disk.total, "used_bytes": disk.used,
                        "free_bytes": disk.free, "used_percent": round(disk.used / disk.total * 100, 1) if disk.total else None},
        "platform": platform.platform(), "sampled_at": datetime.now().astimezone().isoformat(),
    })


def _manifest(
    name: str,
    description: str,
    permission: PermissionTier,
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
    tags: list[str] | None = None,
) -> ToolManifest:
    return ToolManifest(
        name=name,
        description=description,
        permission=permission,
        input_schema={
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
        tags=tags or [],
    )


def build_builtin_registry(
    *,
    policy: PermissionPolicy,
    audit: AuditLog,
    events: EventBus,
    settings: Any,
) -> ToolRegistry:
    registry = ToolRegistry(policy=policy, audit=audit, events=events, settings=settings)
    registry.register(
        _manifest(
            "time.now",
            "Return the current date and time in an IANA timezone.",
            PermissionTier.READ_ONLY,
            {
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone, e.g. Europe/Madrid. Defaults to UTC.",
                }
            },
            tags=["system", "time"],
        ),
        _now,
    )
    registry.register(
        _manifest(
            "memory.save",
            "Store a durable fact, preference, or note about the user.",
            PermissionTier.AUTONOMOUS,
            {
                "content": {"type": "string", "minLength": 1, "maxLength": 20000},
                "kind": {"type": "string", "enum": ["fact", "preference", "note"]},
                "tags": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 40},
                    "maxItems": 20,
                },
            },
            required=["content"],
            tags=["memory"],
        ),
        _memory_save,
    )
    registry.register(
        _manifest(
            "memory.search",
            "Search long-term memory semantically, with lexical fallback.",
            PermissionTier.READ_ONLY,
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            required=["query"],
            tags=["memory"],
        ),
        _memory_search,
    )
    registry.register(
        _manifest(
            "memory.list",
            "List recent memories without searching.",
            PermissionTier.READ_ONLY,
            {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            tags=["memory"],
        ),
        _memory_list,
    )
    registry.register(
        _manifest(
            "memory.forget",
            "Delete a memory. Soft delete by default; hard=true is irreversible.",
            PermissionTier.CONFIRM,
            {
                "id": {"type": "string", "minLength": 1},
                "hard": {"type": "boolean"},
            },
            required=["id"],
            tags=["memory", "destructive"],
        ),
        _memory_forget,
    )
    registry.register(
        _manifest(
            "system.info",
            "Return non-secret host and runtime information.",
            PermissionTier.READ_ONLY,
            {},
            tags=["system"],
        ),
        _system_info,
    )
    registry.register(
        _manifest(
            "system.metrics",
            "Read live CPU utilization, physical memory usage, and system disk capacity.",
            PermissionTier.READ_ONLY,
            {},
            tags=["system", "diagnostics", "metrics"],
        ),
        _system_metrics,
    )
    return registry


def context_events(context: ToolContext) -> EventBus:
    return context.events
