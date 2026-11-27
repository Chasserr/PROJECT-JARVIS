"""Regression tests for the iPhone interface.

The mobile page is a separate surface that reuses the existing dashboard APIs.
These tests drive the real assets at an iPhone viewport (390x844) against a
stubbed backend and lock down tab navigation, chat posting, agent run rendering
with approvals, report links, and the no-horizontal-scroll requirement.
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
IPHONE = {"width": 390, "height": 844}

RUN = {
    "run_id": "1a2b3c4d-0000-4000-8000-000000000001",
    "status": "running",
    "goal": "Summarise the quarterly report",
    "answer": None,
    "plan": {"summary": "plan", "steps": [{"tool": "files.search"}, {"tool": "memory.save"}]},
    "steps": [{"index": 0, "tool": "files.search", "ok": True, "duration_ms": 12}],
    "error": None,
    "approval": None,
    "attempt": 0,
    "role": "engineer",
    "parent_run_id": None,
}

APPROVAL_RUN = {
    **RUN,
    "run_id": "1a2b3c4d-0000-4000-8000-000000000002",
    "status": "awaiting_approval",
    "approval": {
        "run_id": "1a2b3c4d-0000-4000-8000-000000000002",
        "step_index": 0,
        "tool": "shell.run",
        "args": {"argv": ["pytest"]},
        "permission": "confirm",
        "signature": "sig",
    },
}

ROSTER = {
    "orchestrator": "orchestrator",
    "specialist_count": 2,
    "agents": [
        {"id": "orchestrator", "name": "Chief Orchestrator", "status": "connected"},
        {"id": "engineer", "name": "Software Engineer", "status": "connected"},
        {"id": "desktop", "name": "Desktop Agent", "status": "blocked"},
    ],
}

REPORTS = {
    "reports": [
        {"name": "status-report-20261127-120000.md", "size": 2048, "modified": "2026-11-27T12:00:00"},
    ],
    "count": 1,
}


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _json(self, body: Any, status: int = 200) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        routes = {
            "/api/health": lambda: self._json({"app": "online", "model": "test-model", "ollama": True}),
            "/api/core/runs": lambda: self._json({"runs": [RUN, APPROVAL_RUN]}),
            "/api/core/agents": lambda: self._json(ROSTER),
            "/api/reports": lambda: self._json(REPORTS),
            "/api/core/telephony": lambda: self._json(
                {"configured": False, "provider": "none", "missing": ["JARVIS_TELEPHONY_PROVIDER"],
                 "voice": "Polly.Matthew", "language": "en-US", "authorised_callers": 0}
            ),
        }
        if path in routes:
            return routes[path]()
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.server.requests.append(self.path)
        if self.path == "/api/chat":
            return self._json({"reply": "Here is the answer from JARVIS.", "model": "test-model"})
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
            except Exception:  # noqa: BLE001
                continue
        if launched is None:
            pytest.skip("no installed Chrome or Edge is available for Playwright")
        try:
            yield launched
        finally:
            launched.close()


def _serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/mobile.html"


def test_iphone_layout_switches_views_without_overflow(browser) -> None:
    server, url = _serve()
    page = browser.new_page(viewport=IPHONE)
    try:
        page.goto(url, wait_until="domcontentloaded")
        assert page.locator("#view-chat").is_visible()
        assert page.locator("#view-agents").is_hidden()

        page.click('.tab[data-tab="agents"]')
        assert page.locator("#view-agents").is_visible()
        assert page.locator("#view-chat").is_hidden()

        page.click('.tab[data-tab="line"]')
        assert page.locator("#view-line").is_visible()

        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1, f"mobile page scrolls horizontally by {overflow}px"
    finally:
        page.close()
        server.shutdown()
        server.server_close()


def test_chat_posts_the_conversation_and_shows_the_reply(browser) -> None:
    server, url = _serve()
    page = browser.new_page(viewport=IPHONE)
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.fill("#prompt", "What is the status of the project?")
        page.click("#chat .send")
        page.wait_for_selector(".bubble.assistant:has-text('Here is the answer')", timeout=10000)
        assert "/api/chat" in server.requests
        assert page.locator(".bubble.user").first.text_content() == "What is the status of the project?"
    finally:
        page.close()
        server.shutdown()
        server.server_close()


def test_agents_view_shows_progress_and_posts_approval(browser) -> None:
    server, url = _serve()
    page = browser.new_page(viewport=IPHONE)
    page.on("dialog", lambda dialog: dialog.accept())
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.click('.tab[data-tab="agents"]')
        page.wait_for_selector("#runList .run", timeout=10000)
        runs = page.locator("#runList .run")
        assert runs.count() == 2
        assert "1 of 2 steps executed" in page.text_content("#runList")
        assert page.locator("#agentList .state-dot.blocked").count() == 1

        page.click("#runList button.approve")
        page.wait_for_timeout(600)
        assert any("/approve" in path for path in server.requests), server.requests
    finally:
        page.close()
        server.shutdown()
        server.server_close()


def test_reports_are_listed_with_a_download_link(browser) -> None:
    server, url = _serve()
    page = browser.new_page(viewport=IPHONE)
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.click('.tab[data-tab="files"]')
        page.wait_for_selector("#reportList a", timeout=10000)
        link = page.locator("#reportList a").first
        assert link.text_content() == "status-report-20261127-120000.md"
        assert link.get_attribute("href") == "/api/reports/status-report-20261127-120000.md"
        assert "2 KB" in page.text_content("#reportList")
    finally:
        page.close()
        server.shutdown()
        server.server_close()


def test_phone_line_reports_the_missing_configuration(browser) -> None:
    server, url = _serve()
    page = browser.new_page(viewport=IPHONE)
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.click('.tab[data-tab="line"]')
        page.wait_for_function(
            "() => document.getElementById('lineCard').textContent.includes('not configured')",
            timeout=10000,
        )
        text = page.text_content("#lineCard")
        assert "JARVIS_TELEPHONY_PROVIDER" in text
    finally:
        page.close()
        server.shutdown()
        server.server_close()
