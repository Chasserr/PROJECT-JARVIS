"""Camera tools: real behaviour against a scripted transport.

The camera runtime is stubbed, so these tests prove the wiring, the permission
tiers, the blank-frame warning, the vision round-trip and the kill-switch gate —
not a live device. The live run is recorded in the handover.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from jarvis.security.kill_switch import KillSwitch
from jarvis.tools import camera as camera_module

from .test_desktop_creative_tools import context, make_container

FRAME = b"\xff\xd8\xff\xe0" + b"0" * 64


class _Response:
    def __init__(self, payload=None, *, status: int = 200, content: bytes = b"") -> None:
        self._payload = payload if payload is not None else {}
        self.status_code = status
        self.content = content
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class _Client:
    """Records calls and returns one scripted response per path."""

    def __init__(self, routes: dict[str, _Response]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, json=None):
        path = "/" + url.split("/", 3)[3]
        self.calls.append((method, path, json))
        return self.routes.get(path, _Response({"error": "unexpected path"}, status=404))


def _wire(monkeypatch, routes) -> _Client:
    client = _Client(routes)
    monkeypatch.setattr(camera_module, "_client", lambda settings, timeout: client)
    return client


def test_devices_lists_what_windows_reports(tmp_path, monkeypatch):
    _wire(monkeypatch, {"/api/camera/devices": _Response(
        {"devices": [{"index": 0, "name": "Iriun Webcam"}, {"index": 1, "name": "Camo"}]}
    )})
    container = make_container(tmp_path)

    result = asyncio.run(container.registry.execute("camera.devices", {}, context(container)))

    assert result.ok is True
    assert result.output["names"] == ["Iriun Webcam", "Camo"]


def test_devices_reports_no_device_honestly(tmp_path, monkeypatch):
    _wire(monkeypatch, {"/api/camera/devices": _Response({"devices": []})})
    container = make_container(tmp_path)

    result = asyncio.run(container.registry.execute("camera.devices", {}, context(container)))

    assert result.ok is False
    assert "no camera device" in (result.error or "").lower()


def test_capture_warns_about_a_blank_frame(tmp_path, monkeypatch):
    _wire(monkeypatch, {"/api/camera/capture": _Response({
        "device": "Camo", "width": 1280, "height": 720, "blank_frame": True,
        "mean_luma": 0.0, "path": str(tmp_path / "shot.jpg"), "bytes": 7000,
    })})
    container = make_container(tmp_path)

    result = asyncio.run(
        container.registry.execute("camera.capture", {}, context(container), approved=True)
    )

    assert result.ok is True
    assert result.output["blank_frame"] is True
    assert "black frame" in result.output["note"]


def test_analyze_sends_the_frame_as_base64_and_returns_the_description(tmp_path, monkeypatch):
    shot = tmp_path / "shot.jpg"
    shot.write_bytes(FRAME)
    client = _wire(monkeypatch, {
        "/api/camera/capture": _Response({
            "device": "Iriun Webcam", "width": 1280, "height": 720,
            "blank_frame": False, "mean_luma": 12.0, "path": str(shot), "bytes": len(FRAME),
        }),
        "/api/camera/analyze": _Response({"description": "A white desk lamp.", "model": "qwen3.5:4b"}),
    })
    container = make_container(tmp_path)

    result = asyncio.run(
        container.registry.execute(
            "camera.analyze", {"prompt": "What do you see?"}, context(container), approved=True
        )
    )

    assert result.ok is True
    assert result.output["description"] == "A white desk lamp."
    sent = [c for c in client.calls if c[1] == "/api/camera/analyze"][0][2]
    assert base64.b64decode(sent["image"]) == FRAME
    assert sent["prompt"] == "What do you see?"


def test_camera_tools_refuse_when_the_kill_switch_is_engaged(tmp_path, monkeypatch):
    client = _wire(monkeypatch, {"/api/camera/capture": _Response({"blank_frame": False})})
    container = make_container(tmp_path)
    KillSwitch(container.db).engage("test stop")

    result = asyncio.run(
        container.registry.execute("camera.capture", {}, context(container), approved=True)
    )

    assert result.ok is False
    assert "kill switch" in (result.error or "")
    assert client.calls == []


def test_connect_selects_the_named_device(tmp_path, monkeypatch):
    client = _wire(monkeypatch, {
        "/api/camera/select": _Response({"selected": "Camo"}),
        "/api/camera/status": _Response({
            "devices": [{"index": 0, "name": "Iriun Webcam"}, {"index": 1, "name": "Camo"}],
            "selected": "Camo", "default": "Camo",
        }),
    })
    container = make_container(tmp_path)

    result = asyncio.run(
        container.registry.execute("camera.connect", {"device": "Camo"}, context(container), approved=True)
    )

    assert result.ok is True
    assert result.output["device"] == "Camo"
    assert ("POST", "/api/camera/select", {"device": "Camo"}) in client.calls
