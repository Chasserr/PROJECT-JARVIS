"""Camera tools: the PC camera, reached through the desktop runtime.

The capture machinery lives in the desktop process (``app.py``): it enumerates
DirectShow devices, holds one capture lock so two services never fight over the
device, grabs a single frame and reports whether that frame is blank. This module
is a thin typed client, exactly like ``tools/desktop.py``. The core adds the
permission tiers, the approval pause, the audit record and the kill-switch guard
on top; nothing here re-implements device access.

Local only: every call goes to ``settings.pc_runtime_url`` on loopback, and no
frame leaves the machine unless the configured local vision model is asked to
describe it.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from ..security.kill_switch import KillSwitch
from ..security.permissions import PermissionTier
from .manifest import ToolManifest
from .registry import ToolContext, ToolFunc, ToolRegistry, ToolResult, ToolReturn


class CameraError(RuntimeError):
    """The camera runtime is unreachable, refused the request, or saw no camera."""


def _base(settings: Settings) -> str:
    return settings.pc_runtime_url.rstrip("/")


def _client(settings: Settings, timeout: float) -> httpx.AsyncClient:
    """Seam for tests; the runtime sees an ordinary loopback request."""
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


async def _call(
    settings: Settings,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 45.0,
) -> Any:
    url = _base(settings) + path
    try:
        async with _client(settings, timeout) as client:
            response = await client.request(method, url, json=payload)
    except httpx.HTTPError as exc:
        raise CameraError(f"camera runtime unreachable at {_base(settings)}: {exc}") from exc
    if response.status_code >= 400:
        try:
            detail = str(response.json().get("error") or response.text)[:300]
        except ValueError:
            detail = response.text[:300]
        raise CameraError(f"camera runtime refused {path} ({response.status_code}): {detail}")
    try:
        return response.json()
    except ValueError as exc:
        raise CameraError(f"camera runtime returned non-JSON for {path}") from exc


def _blank_note(meta: dict[str, Any]) -> str:
    if meta.get("blank_frame"):
        return (
            " The device produced a pure black frame, which means the virtual camera "
            "has no source attached right now (start the phone/capture app that feeds it)."
        )
    return ""


async def probe_camera(settings: Settings) -> dict[str, Any]:
    """Report whether a camera can be listed and used, for the agent roster probe."""
    try:
        status = await _call(settings, "GET", "/api/camera/status", timeout=20.0)
    except CameraError as exc:
        return {"available": False, "error": str(exc)}
    devices = status.get("devices") or []
    if not devices:
        return {"available": False, "error": "Windows reported no camera device"}
    return {
        "available": True,
        "devices": [d.get("name") for d in devices],
        "default": status.get("default"),
        "detail": f"{len(devices)} camera device(s); default {status.get('default')}",
    }


def _guard(fn: ToolFunc) -> ToolFunc:
    """Refuse camera work while the global kill switch is engaged."""

    async def guarded(args: dict[str, Any], context: ToolContext) -> ToolReturn:
        if context.db is not None and KillSwitch(context.db).is_engaged():
            return ToolResult(ok=False, error="kill switch engaged: camera control is blocked")
        return await fn(args, context)

    return guarded


async def _devices(args: dict[str, Any], context: ToolContext) -> ToolResult:
    data = await _call(context.settings, "GET", "/api/camera/devices", timeout=30.0)
    devices = data.get("devices") or []
    if not devices:
        return ToolResult(ok=False, error="Windows reported no camera device.")
    return ToolResult(
        ok=True,
        output={"devices": devices, "count": len(devices), "names": [d["name"] for d in devices]},
    )


async def _status(args: dict[str, Any], context: ToolContext) -> ToolResult:
    data = await _call(context.settings, "GET", "/api/camera/status", timeout=30.0)
    return ToolResult(ok=True, output=data)


async def _connect(args: dict[str, Any], context: ToolContext) -> ToolResult:
    device = str(args.get("device") or "").strip()
    if device:
        await _call(context.settings, "POST", "/api/camera/select", payload={"device": device})
    status = await _call(context.settings, "GET", "/api/camera/status", timeout=30.0)
    names = [d["name"] for d in status.get("devices") or []]
    if not names:
        return ToolResult(ok=False, error="No camera is attached, so nothing could be connected.")
    chosen = status.get("selected") or status.get("default")
    return ToolResult(
        ok=True,
        output={
            "connected": True,
            "device": chosen,
            "devices": names,
            "note": "Captures are one frame at a time; the camera is released after each shot.",
        },
    )


async def _disconnect(args: dict[str, Any], context: ToolContext) -> ToolResult:
    await _call(context.settings, "POST", "/api/camera/select", payload={"device": ""})
    return ToolResult(
        ok=True,
        output={
            "connected": False,
            "note": "Cleared the selected camera. Captures already taken are unaffected; "
            "the device is released after every shot, so nothing is held open.",
        },
    )


async def _capture(args: dict[str, Any], context: ToolContext) -> ToolResult:
    device = str(args.get("device") or "").strip()
    data = await _call(
        context.settings, "POST", "/api/camera/capture",
        payload={"device": device} if device else {}, timeout=60.0,
    )
    return ToolResult(ok=True, output={**data, "note": ("Frame captured." + _blank_note(data)).strip()})


async def _frame(args: dict[str, Any], context: ToolContext) -> ToolResult:
    captured = await _capture(args, context)
    if not captured.ok:
        return captured
    meta = captured.output or {}
    path = Path(str(meta.get("path", "")))
    if not path.is_file():
        return ToolResult(ok=False, error="The camera reported a frame but the file is missing.")
    return ToolResult(
        ok=True,
        output={
            "path": str(path),
            "bytes": path.stat().st_size,
            "width": meta.get("width"),
            "height": meta.get("height"),
            "blank_frame": meta.get("blank_frame"),
            "note": _blank_note(meta).strip() or "Frame is available on disk for a vision call.",
        },
    )


async def _analyze(args: dict[str, Any], context: ToolContext) -> ToolResult:
    prompt = str(args.get("prompt") or "Describe what you see and identify important objects.")
    if len(prompt) > 1000:
        return ToolResult(ok=False, error="Keep the camera question under 1000 characters.")
    captured = await _capture(args, context)
    if not captured.ok:
        return captured
    meta = captured.output or {}
    path = Path(str(meta.get("path", "")))
    if not path.is_file():
        return ToolResult(ok=False, error="The captured frame is missing, so it cannot be analysed.")
    raw = path.read_bytes()
    if len(raw) > 7 * 1024 * 1024:
        return ToolResult(ok=False, error="The captured frame is too large for the vision endpoint.")
    answer = await _call(
        context.settings, "POST", "/api/camera/analyze",
        payload={"image": base64.b64encode(raw).decode("ascii"), "prompt": prompt},
        timeout=180.0,
    )
    return ToolResult(
        ok=True,
        output={
            "description": answer.get("description"),
            "model": answer.get("model"),
            "frame": str(path),
            "device": meta.get("device"),
            "blank_frame": meta.get("blank_frame"),
            "note": ("Vision answered from the local model." + _blank_note(meta)).strip(),
        },
    )


async def _reconnect(args: dict[str, Any], context: ToolContext) -> ToolResult:
    status = await _call(context.settings, "GET", "/api/camera/status", timeout=30.0)
    names = [d["name"] for d in status.get("devices") or []]
    if not names:
        return ToolResult(ok=False, error="No camera is attached; nothing to reconnect to.")
    chosen = status.get("selected")
    if chosen not in names:
        chosen = names[0]
        await _call(context.settings, "POST", "/api/camera/select", payload={"device": chosen})
    probe = await _call(context.settings, "POST", "/api/camera/capture", payload={}, timeout=60.0)
    return ToolResult(
        ok=True,
        output={
            "reconnected": True,
            "device": chosen,
            "devices": names,
            "frame": probe.get("path"),
            "blank_frame": probe.get("blank_frame"),
            "note": ("Reconnect probe captured a frame." + _blank_note(probe)).strip(),
        },
    )


SCHEMA_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}
DEVICE_SCHEMA = {
    "type": "object",
    "properties": {"device": {"type": "string", "maxLength": 120, "description": "Exact camera name; empty uses the selected or default device."}},
    "additionalProperties": False,
}
ASK_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string", "maxLength": 1000, "description": "Question to ask the vision model about the live frame."},
        "device": {"type": "string", "maxLength": 120},
    },
    "additionalProperties": False,
}


def register_camera_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolManifest(
            name="camera.devices",
            description="List the cameras Windows reports for this PC, with their exact names.",
            permission=PermissionTier.READ_ONLY,
            input_schema=SCHEMA_NO_ARGS,
            timeout_s=45.0,
            tags=["camera", "vision", "hardware"],
        ),
        _guard(_devices),
    )
    registry.register(
        ToolManifest(
            name="camera.status",
            description="Report camera availability: attached devices, the selected device and the last error.",
            permission=PermissionTier.READ_ONLY,
            input_schema=SCHEMA_NO_ARGS,
            timeout_s=45.0,
            tags=["camera", "vision", "hardware"],
        ),
        _guard(_status),
    )
    registry.register(
        ToolManifest(
            name="camera.connect",
            description="Select and verify a camera by name (empty uses the first attached device).",
            permission=PermissionTier.CONFIRM,
            input_schema=DEVICE_SCHEMA,
            timeout_s=60.0,
            tags=["camera", "vision"],
        ),
        _guard(_connect),
    )
    registry.register(
        ToolManifest(
            name="camera.disconnect",
            description="Clear the selected camera so later captures fall back to the default device.",
            permission=PermissionTier.CONFIRM,
            input_schema=SCHEMA_NO_ARGS,
            timeout_s=45.0,
            tags=["camera", "vision"],
        ),
        _guard(_disconnect),
    )
    registry.register(
        ToolManifest(
            name="camera.capture",
            description="Capture exactly one still frame from the camera and save it under the runtime.",
            permission=PermissionTier.CONFIRM,
            input_schema=DEVICE_SCHEMA,
            timeout_s=90.0,
            tags=["camera", "vision"],
        ),
        _guard(_capture),
    )
    registry.register(
        ToolManifest(
            name="camera.get_frame",
            description="Capture a frame and return its path, size and whether the device produced a blank picture.",
            permission=PermissionTier.CONFIRM,
            input_schema=DEVICE_SCHEMA,
            timeout_s=90.0,
            tags=["camera", "vision"],
        ),
        _guard(_frame),
    )
    registry.register(
        ToolManifest(
            name="camera.analyze",
            description=(
                "Look through the camera: capture one frame and have the local vision model "
                "answer a question about it. Use for 'what do you see', 'read this', 'describe the room'."
            ),
            permission=PermissionTier.CONFIRM,
            dangerous=True,
            input_schema=ASK_SCHEMA,
            timeout_s=240.0,
            tags=["camera", "vision", "analysis"],
        ),
        _guard(_analyze),
    )
    registry.register(
        ToolManifest(
            name="camera.reconnect",
            description="Re-probe the cameras, fall back to the first attached device if the selection vanished, and prove it with a frame.",
            permission=PermissionTier.CONFIRM,
            input_schema=SCHEMA_NO_ARGS,
            timeout_s=120.0,
            tags=["camera", "vision", "recovery"],
        ),
        _guard(_reconnect),
    )


__all__ = ["CameraError", "probe_camera", "register_camera_tools"]
