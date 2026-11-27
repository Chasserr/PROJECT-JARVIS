"""Desktop tools: the Windows PC CONTROL runtime, reached through the core.

The mouse/keyboard/file/application machinery already exists in the dashboard
process (``app.py``), where it is bound to loopback, guarded by host/origin
checks and limited to allowlisted keys, shortcuts, folders and file operations.
This module does **not** re-implement any of that. It is a thin, typed client:
the same runtime answers, the same guards apply, and the core adds its own
permission tiers, approval pause and audit record on top.

Every call is made over loopback to ``settings.pc_runtime_url``; a request that
the runtime refuses is surfaced as an error, never as a success.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from ..security.permissions import PermissionTier
from .manifest import ToolManifest
from .registry import ToolContext, ToolRegistry, ToolResult


class DesktopRuntimeError(RuntimeError):
    """The PC CONTROL runtime is unreachable or refused the request."""


def runtime_base(settings: Settings) -> str:
    return settings.pc_runtime_url.rstrip("/")


def _http_client(settings: Settings, timeout: float) -> httpx.AsyncClient:
    """Seam for tests; the runtime sees an ordinary loopback request."""
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


async def _request(
    settings: Settings,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    expect_binary: bool = False,
) -> Any:
    url = runtime_base(settings) + path
    try:
        async with _http_client(settings, timeout) as client:
            response = await client.request(method, url, json=payload, headers=headers or {})
    except httpx.HTTPError as exc:
        raise DesktopRuntimeError(f"PC runtime unreachable at {runtime_base(settings)}: {exc}") from exc
    if response.status_code >= 400:
        detail: str
        try:
            data = response.json()
            detail = str(data.get("error") or data)[:400]
        except ValueError:
            detail = response.text[:400]
        raise DesktopRuntimeError(f"PC runtime refused {path} ({response.status_code}): {detail}")
    if expect_binary:
        return response.content
    try:
        return response.json()
    except ValueError as exc:
        raise DesktopRuntimeError(f"PC runtime returned non-JSON for {path}") from exc


async def probe_desktop(settings: Settings) -> dict[str, Any]:
    """Prove the PC runtime answers with real screen geometry."""
    try:
        data = await _request(settings, "GET", "/api/computer/status", timeout=8.0)
    except DesktopRuntimeError as exc:
        return {"available": False, "error": str(exc)}
    screen = data.get("screen") or {}
    if not screen.get("width") or not screen.get("height"):
        return {"available": False, "error": "PC runtime answered without screen dimensions"}
    try:
        input_state = await _request(settings, "GET", "/api/computer/input-status", timeout=8.0)
    except DesktopRuntimeError as exc:
        return {"available": False, "error": str(exc)}
    if not input_state.get("attached"):
        return {
            "available": False,
            "screen": screen,
            "error": (
                "the PC runtime cannot see a foreground window, so mouse and keyboard "
                "input has no target: start JARVIS from the signed-in desktop session "
                "and unlock the screen"
            ),
        }
    return {
        "available": True,
        "screen": screen,
        "active_window": str(input_state.get("foreground") or data.get("active_window") or ""),
        "detail": (
            f"PC runtime on {runtime_base(settings)} controls a "
            f"{screen['width']}x{screen['height']} desktop; foreground window "
            f"{input_state.get('foreground') or '(none)'}"
        ),
    }


async def _status(args: dict[str, Any], context: ToolContext) -> ToolResult:
    data = await _request(context.settings, "GET", "/api/computer/status")
    return ToolResult(ok=True, output=data)


async def _windows(args: dict[str, Any], context: ToolContext) -> ToolResult:
    data = await _request(context.settings, "GET", "/api/running")
    apps = data.get("apps", []) if isinstance(data, dict) else []
    return ToolResult(ok=True, output={"apps": apps, "count": len(apps)})


async def _inspect(args: dict[str, Any], context: ToolContext) -> ToolResult:
    window = str(args.get("window") or "")
    data = await _request(
        context.settings,
        "GET",
        "/api/computer/inspect",
        headers={"X-Jarvis-Window": window},
    )
    return ToolResult(ok=True, output=data)


async def _screenshot(args: dict[str, Any], context: ToolContext) -> ToolResult:
    body = await _request(
        context.settings, "GET", "/api/computer/screenshot", timeout=45.0, expect_binary=True
    )
    if not body.startswith(b"\x89PNG"):
        raise DesktopRuntimeError("the runtime did not return a PNG image")
    folder = Path(context.settings.data_dir) / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"screen-{int(time.time())}.png"
    target.write_bytes(body)
    return ToolResult(
        ok=True,
        output={"path": str(target), "bytes": len(body), "format": "png"},
    )


async def _action(args: dict[str, Any], context: ToolContext) -> ToolResult:
    payload = {key: value for key, value in args.items() if value is not None}
    # The runtime validates coordinates against the live screen and rejects any
    # key, shortcut or scroll amount outside its own allowlists.
    data = await _request(context.settings, "POST", "/api/computer/action", payload=payload)
    return ToolResult(ok=True, output=data)


async def _focus(args: dict[str, Any], context: ToolContext) -> ToolResult:
    data = await _request(
        context.settings,
        "POST",
        "/api/computer/focus",
        payload={"window": str(args["window"])},
        timeout=30.0,
    )
    return ToolResult(ok=True, output=data)


async def _open_app(args: dict[str, Any], context: ToolContext) -> ToolResult:
    data = await _request(
        context.settings,
        "POST",
        "/api/desktop/open",
        payload={"app": str(args["app"])},
        timeout=45.0,
    )
    return ToolResult(ok=True, output=data)


async def _close_app(args: dict[str, Any], context: ToolContext) -> ToolResult:
    data = await _request(
        context.settings,
        "POST",
        "/api/desktop/close",
        payload={"app": str(args["app"])},
        timeout=45.0,
    )
    return ToolResult(ok=True, output=data)


async def _files(args: dict[str, Any], context: ToolContext) -> ToolResult:
    payload = {key: value for key, value in args.items() if value is not None}
    data = await _request(context.settings, "POST", "/api/computer/files", payload=payload)
    return ToolResult(ok=True, output=data)


_ACTION_DOC = (
    "Run one approved mouse or keyboard action on this Windows desktop. The PC "
    "runtime validates coordinates against the live screen and only accepts its "
    "allowlisted keys and shortcuts."
)

_SCREEN_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "click",
                "double_click",
                "right_click",
                "move",
                "drag",
                "scroll",
                "type",
                "press",
                "hotkey",
            ],
        },
        "x": {"type": "integer", "minimum": 0},
        "y": {"type": "integer", "minimum": 0},
        "start_x": {"type": "integer", "minimum": 0},
        "start_y": {"type": "integer", "minimum": 0},
        "amount": {"type": "integer", "minimum": -20, "maximum": 20},
        "text": {"type": "string", "maxLength": 3000},
        "key": {"type": "string", "maxLength": 20},
        "keys": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["action"],
    "additionalProperties": False,
}


def register_desktop_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolManifest(
            name="desktop.status",
            description=(
                "Report real state of this Windows desktop: screen size, the "
                "foreground window and the busiest processes."
            ),
            permission=PermissionTier.READ_ONLY,
            timeout_s=60.0,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            tags=["desktop", "pc", "windows"],
        ),
        _status,
    )
    registry.register(
        ToolManifest(
            name="desktop.windows",
            description="List running applications that own a visible window, with their titles.",
            permission=PermissionTier.READ_ONLY,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            tags=["desktop", "pc", "windows"],
        ),
        _windows,
    )
    registry.register(
        ToolManifest(
            name="desktop.inspect",
            description=(
                "Inspect the accessible controls of a window (buttons, fields, "
                "lists) so a UI action can target a real control instead of a guess."
            ),
            permission=PermissionTier.READ_ONLY,
            input_schema={
                "type": "object",
                "properties": {
                    "window": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "Window title fragment; empty means the foreground window.",
                    }
                },
                "additionalProperties": False,
            },
            timeout_s=60.0,
            tags=["desktop", "pc", "ui"],
        ),
        _inspect,
    )
    registry.register(
        ToolManifest(
            name="desktop.screenshot",
            description="Capture the current desktop as a PNG and save it under the data directory.",
            permission=PermissionTier.CONFIRM,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            timeout_s=60.0,
            tags=["desktop", "pc", "screen"],
        ),
        _screenshot,
    )
    registry.register(
        ToolManifest(
            name="desktop.action",
            description=_ACTION_DOC,
            permission=PermissionTier.CONFIRM,
            dangerous=True,
            input_schema=_SCREEN_SCHEMA,
            timeout_s=60.0,
            tags=["desktop", "pc", "mouse", "keyboard"],
        ),
        _action,
    )
    registry.register(
        ToolManifest(
            name="desktop.focus",
            description=(
                "Bring one visible window matching a title fragment to the front, so "
                "the following keyboard input has a known target."
            ),
            permission=PermissionTier.CONFIRM,
            input_schema={
                "type": "object",
                "properties": {"window": {"type": "string", "minLength": 1, "maxLength": 200}},
                "required": ["window"],
                "additionalProperties": False,
            },
            timeout_s=45.0,
            tags=["desktop", "pc", "windows"],
        ),
        _focus,
    )
    registry.register(
        ToolManifest(
            name="desktop.open_app",
            description=(
                "Launch an application that exists in the Windows Start menu. The "
                "name must match exactly one catalogue entry."
            ),
            permission=PermissionTier.CONFIRM,
            dangerous=True,
            input_schema={
                "type": "object",
                "properties": {"app": {"type": "string", "minLength": 1, "maxLength": 100}},
                "required": ["app"],
                "additionalProperties": False,
            },
            timeout_s=60.0,
            tags=["desktop", "pc", "apps"],
        ),
        _open_app,
    )
    registry.register(
        ToolManifest(
            name="desktop.close_app",
            description="Ask one running application to close, matched by its window title.",
            permission=PermissionTier.CONFIRM,
            dangerous=True,
            input_schema={
                "type": "object",
                "properties": {"app": {"type": "string", "minLength": 1, "maxLength": 100}},
                "required": ["app"],
                "additionalProperties": False,
            },
            timeout_s=45.0,
            tags=["desktop", "pc", "apps"],
        ),
        _close_app,
    )
    registry.register(
        ToolManifest(
            name="desktop.files",
            description=(
                "Perform one approved file operation through the PC runtime: open, "
                "rename, move, or send to the Recycle Bin (trash needs confirm=true)."
            ),
            permission=PermissionTier.CONFIRM,
            dangerous=True,
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["open", "rename", "move", "trash"]},
                    "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "name": {"type": "string", "maxLength": 255},
                    "destination": {"type": "string", "maxLength": 4096},
                    "confirm": {"type": "boolean"},
                },
                "required": ["action", "path"],
                "additionalProperties": False,
            },
            timeout_s=60.0,
            tags=["desktop", "pc", "files"],
        ),
        _files,
    )


__all__ = ["DesktopRuntimeError", "probe_desktop", "register_desktop_tools", "runtime_base"]
