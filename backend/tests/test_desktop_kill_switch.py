"""Desktop tools must refuse while the global kill switch is engaged.

The transport is stubbed, so anything that reaches the runtime shows up as a
recorded call. An engaged switch must produce zero calls: the guard runs before
any mouse, keyboard or file request leaves the core.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from jarvis.security.kill_switch import KillSwitch
from jarvis.tools import desktop as desktop_module

from .test_desktop_creative_tools import context, make_container


class _StubResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200
        self.content = b""
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _StubClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self) -> _StubClient:
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def request(self, method, url, json=None, headers=None):
        self.calls.append((method, url))
        return _StubResponse(self._payload)


PAYLOAD = {"screen": {"width": 1920, "height": 1080}, "active_window": "Notepad", "processes": []}


def _wire(monkeypatch, payload=PAYLOAD) -> _StubClient:
    client = _StubClient(payload)
    monkeypatch.setattr(desktop_module, "_http_client", lambda settings, timeout: client)
    return client


def test_read_only_desktop_tool_refuses_when_kill_switch_engaged(tmp_path, monkeypatch):
    client = _wire(monkeypatch)
    container = make_container(tmp_path)
    KillSwitch(container.db).engage("test stop")

    result = asyncio.run(container.registry.execute("desktop.status", {}, context(container)))

    assert result.ok is False
    assert "kill switch" in (result.error or "")
    assert client.calls == [], "an engaged kill switch must not reach the desktop runtime"


def test_dangerous_desktop_tool_refuses_even_when_approved(tmp_path, monkeypatch):
    client = _wire(monkeypatch)
    container = make_container(tmp_path)
    KillSwitch(container.db).engage("test stop")

    result = asyncio.run(
        container.registry.execute("desktop.screenshot", {}, context(container), approved=True)
    )

    assert result.ok is False
    assert "kill switch" in (result.error or "")
    assert client.calls == []


def test_desktop_tool_runs_again_after_release(tmp_path, monkeypatch):
    client = _wire(monkeypatch)
    container = make_container(tmp_path)
    switch = KillSwitch(container.db)
    switch.engage("test stop")
    switch.release()

    result = asyncio.run(container.registry.execute("desktop.status", {}, context(container)))

    assert result.ok is True
    assert result.output["screen"]["width"] == 1920
    assert len(client.calls) == 1
