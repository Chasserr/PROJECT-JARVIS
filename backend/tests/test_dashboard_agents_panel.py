"""Regression tests for the legacy dashboard's Agents rail button.

The defect these lock down: inside ``@media (max-width:850px)`` in
``web/openjarvis.css`` every rail label was hidden (``.rail-item span
{display:none}``) while ``web/style.css`` forced ``width:100%`` on the same
buttons. With the rail switched to ``flex-direction:row`` that collapsed eight
buttons into ~18px blank squares, so the Agents button had no readable content
and no usable click target — a physical mouse click could not open the roster.

These tests drive a real installed browser with real mouse events against a
real HTTP server. Playwright's ``page.click`` performs its own actionability and
hit-testing checks, so the suite fails if labels, sizing, clipping or event
wiring regress again.
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

# Two layouts: the narrow/mobile one that was broken, and a normal desktop one.
VIEWPORTS = [(420, 820), (1400, 900)]


def _agent(role_id: str, name: str, capability: str) -> dict[str, Any]:
    return {
        "id": role_id,
        "name": name,
        "description": f"{name} description.",
        "backend": "role-scoped AgentLoop run",
        "capability": capability,
        "can_delegate": role_id == "orchestrator",
        "tools": ["memory.search"],
        "available_tools": sorted(["memory.search", "agent.roster"]),
        "missing_tools": [],
        "notes": "",
    }


ROSTER = {
    "orchestrator": "orchestrator",
    "specialist_count": 10,
    "agents": [
        _agent("orchestrator", "Chief Orchestrator", "routing"),
        _agent("engineer", "Software Engineer", "partial"),
        _agent("research", "Research Agent", "partial"),
        _agent("security", "Security Agent", "partial"),
        _agent("testing", "Testing Agent", "partial"),
        _agent("browser", "Browser Agent", "partial"),
        _agent("desktop", "Desktop Agent", "partial"),
        _agent("creative", "Creative Agent", "partial"),
        _agent("memory", "Memory Agent", "full"),
        _agent("critic", "Critic Agent", "full"),
        _agent("writer", "Documentation Agent", "full"),
    ],
}

RAIL_LABELS = [
    "Chat",
    "Agents",
    "Workflows",
    "PC Control",
    "Files",
    "Memory",
    "Tools",
    "Settings",
]


class _DashboardHandler(SimpleHTTPRequestHandler):
    """Serve the real ``web/`` assets and stub only the core agent roster."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path.split("?")[0] == "/api/core/agents":
            body = json.dumps(ROSTER).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.split("?")[0] == "/api/health":
            body = json.dumps({"app": "online", "model": "test-model"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args: Any) -> None:  # silence test output
        return


@pytest.fixture(scope="module")
def dashboard_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


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


def _open(browser, dashboard_url: str, width: int, height: int):
    page = browser.new_page(viewport={"width": width, "height": height})
    page.goto(dashboard_url, wait_until="domcontentloaded")
    return page


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_rail_labels_are_visible_and_readable(browser, dashboard_url, width, height) -> None:
    """Regression: `.rail-item span{display:none}` hid every rail label."""
    page = _open(browser, dashboard_url, width, height)
    try:
        labels = page.eval_on_selector_all(
            ".left-rail .rail-item span",
            "els => els.map(e => ({text: e.innerText.trim(), display: getComputedStyle(e).display,"
            " width: Math.round(e.getBoundingClientRect().width),"
            " height: Math.round(e.getBoundingClientRect().height)}))",
        )
        assert len(labels) >= len(RAIL_LABELS), labels
        for item in labels:
            assert item["display"] != "none", item
            assert item["text"], f"rail button has no visible label: {item}"
            assert item["width"] > 0 and item["height"] > 0, item
        assert [item["text"] for item in labels] == RAIL_LABELS
    finally:
        page.close()


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_agents_button_keeps_a_usable_click_target(browser, dashboard_url, width, height) -> None:
    """Regression: flex row + forced width:100% squeezed the button to ~18px."""
    page = _open(browser, dashboard_url, width, height)
    try:
        box = page.locator("#railAgents").bounding_box()
        assert box is not None, "Agents button has no layout box"
        assert box["width"] >= 40, f"Agents button is only {box['width']}px wide"
        assert box["height"] >= 34, f"Agents button is only {box['height']}px tall"
        # The button must not be clipped away by an ancestor.
        visible = page.locator("#railAgents").evaluate(
            "el => { const r = el.getBoundingClientRect();"
            " const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);"
            " return !!(top && (top === el || el.contains(top))); }"
        )
        assert visible is True, "another element covers the Agents button"
    finally:
        page.close()


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_real_mouse_click_opens_the_agents_panel(browser, dashboard_url, width, height) -> None:
    """A real pointer click must open the roster via #railAgents."""
    page = _open(browser, dashboard_url, width, height)
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#agentCards .agent-card').length > 0",
            timeout=10000,
        )
        assert page.locator("#agentDirectory").is_hidden()

        # Real mouse click; Playwright hit-tests the target the way a user clicks.
        page.locator("#railAgents").click()

        assert page.locator("#agentDirectory").is_visible()
        cards = page.locator("#agentCards .agent-card")
        assert cards.count() == 11
        names = page.eval_on_selector_all(
            "#agentCards .agent-card h3", "els => els.map(e => e.innerText.trim())"
        )
        assert names[0] == "Chief Orchestrator"
        assert "Research Agent" in names
        assert "Memory Agent" in names
    finally:
        page.close()


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_close_button_hides_the_agents_panel(browser, dashboard_url, width, height) -> None:
    page = _open(browser, dashboard_url, width, height)
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#agentCards .agent-card').length > 0",
            timeout=10000,
        )
        page.locator("#railAgents").click()
        assert page.locator("#agentDirectory").is_visible()

        page.locator("#closeAgentDirectory").click()
        assert page.locator("#agentDirectory").is_hidden()
    finally:
        page.close()


def test_agents_panel_toggles_repeatedly(browser, dashboard_url) -> None:
    """Opening and closing must stay stable across repeated real clicks."""
    page = _open(browser, dashboard_url, 420, 820)
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#agentCards .agent-card').length > 0",
            timeout=10000,
        )
        for _ in range(3):
            page.locator("#railAgents").click()
            assert page.locator("#agentDirectory").is_visible()
            page.locator("#closeAgentDirectory").click()
            assert page.locator("#agentDirectory").is_hidden()
    finally:
        page.close()
