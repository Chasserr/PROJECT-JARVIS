"""Dashboard token resolution and bounded UI Automation inspection.

Both defects were fixed in the desktop process (root ``app.py``), so these tests
import that module directly. The UI Automation child process is stubbed: the
point under test is the timeout/error contract and the JSON handoff, not a live
window.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def dashboard():
    spec = importlib.util.spec_from_file_location(
        "jarvis_dashboard_under_test", PROJECT_ROOT / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_env(root: Path, value: str) -> None:
    backend = root / "backend"
    backend.mkdir(parents=True, exist_ok=True)
    (backend / ".env").write_text(f"JARVIS_API_TOKEN={value}\n", encoding="utf-8")


def test_api_token_prefers_environment(dashboard, tmp_path, monkeypatch):
    """The core lets the environment win, so the dashboard must too."""
    _write_env(tmp_path, "from-file")
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    monkeypatch.setenv("JARVIS_API_TOKEN", "from-environment")
    assert dashboard.api_token() == "from-environment"


def test_api_token_falls_back_to_env_file(dashboard, tmp_path, monkeypatch):
    _write_env(tmp_path, "from-file")
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    monkeypatch.delenv("JARVIS_API_TOKEN", raising=False)
    assert dashboard.api_token() == "from-file"


def test_api_token_unwraps_quotes(dashboard, tmp_path, monkeypatch):
    _write_env(tmp_path, '"quoted-token"')
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    monkeypatch.delenv("JARVIS_API_TOKEN", raising=False)
    assert dashboard.api_token() == "quoted-token"


def test_api_token_without_any_source_is_empty(dashboard, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    monkeypatch.delenv("JARVIS_API_TOKEN", raising=False)
    assert dashboard.api_token() == ""


def _fake_subprocess(monkeypatch, run):
    fake = types.SimpleNamespace(
        run=run,
        TimeoutExpired=subprocess.TimeoutExpired,
        CREATE_NO_WINDOW=0x08000000,
    )
    monkeypatch.setattr(dashboard_module(), "subprocess", fake)
    return fake


def dashboard_module():
    """The most recently imported dashboard module (see the fixture)."""
    return sys.modules["jarvis_dashboard_under_test"]


def test_inspect_ui_bounded_returns_child_payload(dashboard, monkeypatch):
    payload = {"window": "Notepad", "controls": [{"name": "Save", "type": "Button"}], "windows": []}

    def run(cmd, **kwargs):
        Path(cmd[4]).write_text(json.dumps(payload), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    _fake_subprocess(monkeypatch, run)
    assert dashboard.inspect_ui_bounded("notepad", timeout=5) == payload


def test_inspect_ui_bounded_raises_timeout_error(dashboard, monkeypatch):
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 10))

    _fake_subprocess(monkeypatch, run)
    with pytest.raises(TimeoutError) as excinfo:
        dashboard.inspect_ui_bounded("", timeout=10)
    assert "did not answer" in str(excinfo.value)


def test_inspect_ui_bounded_surfaces_child_failure(dashboard, monkeypatch):
    def run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="uia exploded")

    _fake_subprocess(monkeypatch, run)
    with pytest.raises(RuntimeError) as excinfo:
        dashboard.inspect_ui_bounded("", timeout=10)
    assert "uia exploded" in str(excinfo.value)
