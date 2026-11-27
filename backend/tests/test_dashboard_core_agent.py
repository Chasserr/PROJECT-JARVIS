"""Regression tests for the redesigned Core Agent panel.

The panel was re-skinned only. These tests drive the real assets in ``web/``
against stubbed Core responses and lock down four things that the redesign must
not break:

1. every section the layout promises exists and is reachable;
2. the KPI numbers and charts are derived from the response, never invented;
3. empty and error states are explicit instead of showing fake progress;
4. the approval control still posts to the real Core endpoint, and the rest of
   the dashboard (rail, orb, PC Control, Workflow Studio, settings) is untouched.
"""

from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

sync_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright is required for dashboard regression tests"
)
sync_playwright = sync_api.sync_playwright

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def _run(
    run_id: str = "1a2b3c4d-0000-4000-8000-000000000001",
    status: str = "completed",
    role: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    plan: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": status,
        "goal": "Summarise the project status",
        "answer": "Done." if status == "completed" else None,
        "plan": {"summary": "plan", "steps": plan or []},
        "steps": steps or [],
        "error": None,
        "approval": None,
        "attempt": 0,
        "role": role,
        "parent_run_id": None,
        **extra,
    }


def _agent(agent_id: str, name: str, status: str) -> dict[str, Any]:
    return {
        "id": agent_id, "name": name, "description": name, "backend": "loop",
        "capability": "full", "can_delegate": False, "tools": [], "available_tools": [],
        "missing_tools": [], "notes": "", "status": status, "requires": [],
        "unmet_requirements": [], "status_detail": "",
    }


ROSTER = {
    "orchestrator": "orchestrator",
    "specialist_count": 3,
    "agents": [
        _agent("orchestrator", "Chief Orchestrator", "connected"),
        _agent("engineer", "Software Engineer", "connected"),
        _agent("research", "Research Agent", "partial"),
        _agent("desktop", "Desktop Agent", "blocked"),
    ],
}

TOOLS = [
    {"name": "shell.run", "description": "run", "permission": "confirm"},
    {"name": "time.now", "description": "clock", "permission": "read_only"},
]

HEALTH = {
    "app": "online", "model": "test-model", "memory_count": 3,
    "agent_core": {"status": "ok", "database": True},
}


class _Handler(SimpleHTTPRequestHandler):
    """Serve the real ``web/`` tree and stub only the Core endpoints."""

    payload: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _json(self, body: Any, status: int = 200) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = self.path.split("?")[0]
        routes = {
            "/api/core/runs": lambda: self._json({"runs": self.payload.get("runs", [])}),
            "/api/core/agents": lambda: self._json(ROSTER),
            "/api/core/tools": lambda: self._json(TOOLS),
            "/api/health": lambda: self._json(HEALTH),
        }
        if path in routes:
            if path == "/api/core/runs" and self.payload.get("runs_error"):
                return self._json({"detail": "core unavailable"}, 503)
            return routes[path]()
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        self.server.requests.append((self.path, body))
        return self._json({"ok": True})

    def log_message(self, *args: Any) -> None:
        return


@pytest.fixture(scope="module")
def browser():
    if not WEB_DIR.is_dir():
        pytest.skip(f"dashboard assets not found at {WEB_DIR}")
    with sync_playwright() as playwright:
        launched = None
        for channel in ("chrome", "msedge"):
            try:
                launched = playwright.chromium.launch(channel=channel)
                break
            except Exception:  # noqa: BLE001 - try the next installed browser
                continue
        if launched is None:
            pytest.skip("no installed Chrome or Edge is available for Playwright")
        try:
            yield launched
        finally:
            launched.close()


def _serve(payload: dict[str, Any]):
    handler = type("Handler", (_Handler,), {"payload": payload})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def _panel_page(browser, url: str):
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.goto(url, wait_until="domcontentloaded")
    page.click("#coreAgentBtn")
    page.wait_for_function(
        "() => document.getElementById('caStatusText').textContent !== 'Checking Core…'",
        timeout=15000,
    )
    return page


def test_kpis_and_charts_come_from_core_data(browser) -> None:
    runs = [
        _run(status="running", steps=[{"index": 0, "tool": "time.now", "ok": True, "duration_ms": 4}]),
        _run("1a2b3c4d-0000-4000-8000-000000000002", status="running", role="engineer"),
        _run("1a2b3c4d-0000-4000-8000-000000000003", status="completed", role="engineer"),
        _run("1a2b3c4d-0000-4000-8000-000000000004", status="completed"),
        _run("1a2b3c4d-0000-4000-8000-000000000005", status="completed"),
        _run("1a2b3c4d-0000-4000-8000-000000000006", status="failed"),
        _run("1a2b3c4d-0000-4000-8000-000000000007", status="cancelled"),
    ]
    server, url = _serve({"runs": runs})
    page = _panel_page(browser, url)
    try:
        assert page.text_content("#caKpiActive") == "2"
        assert page.text_content("#caKpiCompleted") == "3"
        # Distinct roles across the two active runs: orchestrator + engineer.
        assert page.text_content("#caKpiAgents") == "2"
        assert page.text_content("#caKpiSuccess") == "75%"
        assert page.locator("#caExecutionChart svg").count() == 1
        assert page.locator("#caWorkloadChart svg").count() == 1
        assert page.text_content("#coreAgentStatus").startswith("Core online")
    finally:
        page.close()
        server.shutdown()
        server.server_close()


def test_empty_state_reports_no_data_instead_of_zero_progress(browser) -> None:
    server, url = _serve({"runs": []})
    page = _panel_page(browser, url)
    try:
        assert page.text_content("#caKpiActive") == "0"
        assert page.text_content("#caKpiSuccess") == "—"
        assert "no finished runs" in page.text_content("#caKpiSuccessNote")
        assert page.locator("#caExecutionChart svg").count() == 0
        assert "No runs yet" in page.text_content("#caExecutionChart")
        assert "No active task" in page.text_content("#caCurrentTask")
    finally:
        page.close()
        server.shutdown()
        server.server_close()


def test_core_outage_shows_an_error_state(browser) -> None:
    server, url = _serve({"runs": [], "runs_error": True})
    page = _panel_page(browser, url)
    try:
        assert page.text_content("#caStatusText") == "Core unreachable"
        assert page.text_content("#caKpiActive") == "—"
        assert page.locator("#caExecutionChart .ca-error").count() == 1
        assert page.locator("#caCurrentTask .ca-error").count() == 1
    finally:
        page.close()
        server.shutdown()
        server.server_close()


def test_approval_control_posts_to_the_real_core_endpoint(browser) -> None:
    approval = {
        "run_id": "1a2b3c4d-0000-4000-8000-000000000009",
        "step_index": 0, "tool": "shell.run", "args": {"argv": ["pytest"]},
        "permission": "confirm", "signature": "sig",
    }
    runs = [_run("1a2b3c4d-0000-4000-8000-000000000009", status="awaiting_approval", approval=approval)]
    server, url = _serve({"runs": runs})
    page = _panel_page(browser, url)
    page.on("dialog", lambda dialog: dialog.accept())
    try:
        assert "Permission required: confirm" in page.text_content("#caCurrentTask")
        page.click("#caCurrentTask button.ca-btn--approve")
        page.wait_for_timeout(600)
        assert any(
            path.endswith("/api/core/runs/1a2b3c4d-0000-4000-8000-000000000009/approve")
            for path, _ in server.requests
        ), server.requests
    finally:
        page.close()
        server.shutdown()
        server.server_close()


def test_shell_and_other_modules_are_untouched(browser) -> None:
    server, url = _serve({"runs": []})
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    try:
        page.goto(url, wait_until="domcontentloaded")
        labels = page.eval_on_selector_all(
            ".left-rail .rail-item span", "els => els.map(e => e.innerText.trim())"
        )
        assert labels == [
            "Chat", "Agents", "Workflows", "Visuals", "PC Control",
            "Files", "Memory", "Tools", "Settings",
        ]
        for selector in ("#mic", "#computerPanel", "#workflowPanel", "#agentDirectory", "#settings"):
            assert page.locator(selector).count() == 1, selector

        page.click("#coreAgentBtn")
        page.wait_for_timeout(400)
        # Opening the panel must not remove or restyle the rest of the shell.
        assert page.locator("#coreAgentPanel").is_visible()
        assert page.locator(".left-rail .rail-item").count() == 9
        assert page.locator("#mic").count() == 1

        page.click("#closeCoreAgent")
        page.wait_for_timeout(200)
        assert page.locator("#coreAgentPanel").is_hidden()
        assert page.locator("#mic").is_visible()
    finally:
        page.close()
        server.shutdown()
        server.server_close()
