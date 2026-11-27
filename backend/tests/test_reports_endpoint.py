"""Security tests for the /api/reports read-only routes.

These drive the real ``app.py`` handler (the dashboard server) over HTTP with a
random port, using the Host header the handler expects. The reports directory is
redirected to a temporary tree, so a traversal attempt that escaped the directory
would become visible instead of silently hitting the real project data.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app.py"

# The handler only accepts these; a random test port is reached by sending the
# same Host header a browser on the dashboard would send.
TRUSTED_HOST = "127.0.0.1:8765"


def _load_app() -> Any:
    spec = importlib.util.spec_from_file_location("jarvis_legacy_app", APP_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.skip("app.py is not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def app_module() -> Any:
    if not APP_PATH.is_file():  # pragma: no cover - defensive
        pytest.skip("dashboard server not found")
    return _load_app()


@pytest.fixture()
def server(app_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A real HTTP server whose ROOT is a temporary copy of the project layout."""
    web = tmp_path / "web"
    web.mkdir()
    reports = tmp_path / "backend" / "data" / "reports"
    reports.mkdir(parents=True)

    (reports / "status-report.md").write_text("# Status\nAll good.\n", encoding="utf-8")
    (reports / "quarterly.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (reports / "notes.txt").write_text("notes", encoding="utf-8")
    (reports / "data.json").write_text('{"ok": true}', encoding="utf-8")
    (reports / "ignored.exe").write_bytes(b"MZ")
    # Fixed mtimes make the newest-first ordering deterministic.
    for offset, name in enumerate(("status-report.md", "quarterly.pdf", "data.json", "notes.txt", "ignored.exe")):
        stamp = 1_700_000_000 + offset
        os.utime(reports / name, (stamp, stamp))
    # A secret that lives OUTSIDE the reports directory. Traversal must not reach it.
    (tmp_path / "backend" / "data" / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")

    monkeypatch.setattr(app_module, "ROOT", tmp_path)
    httpd = app_module.ThreadingHTTPServer(("127.0.0.1", 0), app_module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], reports
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(port: int, path: str, host: str = TRUSTED_HOST):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", path, headers={"Host": host})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_list_returns_only_report_files(server) -> None:
    port, _ = server
    status, headers, body = _get(port, "/api/reports")
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    payload = json.loads(body)
    names = [item["name"] for item in payload["reports"]]
    assert names == ["notes.txt", "data.json", "quarterly.pdf", "status-report.md"]
    # Executables and anything else are not advertised.
    assert "ignored.exe" not in names
    assert payload["count"] == len(names)
    for item in payload["reports"]:
        assert item["size"] > 0
        assert item["modified"]
    assert "secret.txt" not in names


def test_markdown_download_has_an_inline_disposition(server) -> None:
    port, _ = server
    status, headers, body = _get(port, "/api/reports/status-report.md")
    assert status == 200
    assert headers["Content-Type"].startswith("text/markdown")
    assert headers["Content-Disposition"] == 'inline; filename="status-report.md"'
    assert headers["Cache-Control"] == "no-store"
    assert body.startswith(b"# Status")


def test_pdf_download_uses_the_pdf_content_type(server) -> None:
    port, _ = server
    status, headers, body = _get(port, "/api/reports/quarterly.pdf")
    assert status == 200
    assert headers["Content-Type"] == "application/pdf"
    assert body.startswith(b"%PDF")


@pytest.mark.parametrize(
    ("name", "content_type"),
    [("notes.txt", "text/plain; charset=utf-8"), ("data.json", "application/json; charset=utf-8")],
)
def test_each_extension_gets_an_honest_content_type(server, name: str, content_type: str) -> None:
    port, _ = server
    status, headers, _ = _get(port, "/api/reports/" + name)
    assert status == 200
    assert headers["Content-Type"] == content_type


@pytest.mark.parametrize(
    "path",
    [
        "/api/reports/%2e%2e%2fsecret.txt",
        "/api/reports/..%2Fsecret.txt",
        "/api/reports/..%5Csecret.txt",
        "/api/reports/....%2f%2fsecret.txt",
        "/api/reports/%2e%2e%2f%2e%2e%2fbackend%2fdata%2fsecret.txt",
        "/api/reports/..%2Fbackend%2Fdata%2Fsecret.txt",
    ],
)
def test_traversal_cannot_read_outside_the_reports_directory(server, path: str) -> None:
    port, _ = server
    status, _, body = _get(port, path)
    assert status == 404, (path, status, body[:200])
    assert b"TOP-SECRET" not in body


def test_absolute_paths_are_reduced_to_a_name_inside_reports(server) -> None:
    port, _ = server
    status, _, body = _get(port, "/api/reports/C%3A%5CWindows%5Cwin.ini")
    assert status == 404
    assert b"[fonts]" not in body.lower()


def test_a_query_string_does_not_break_the_download(server) -> None:
    port, _ = server
    status, headers, body = _get(port, "/api/reports/status-report.md?v=2")
    assert status == 200
    assert headers["Content-Disposition"] == 'inline; filename="status-report.md"'
    assert body.startswith(b"# Status")


def test_a_missing_report_is_a_404_not_a_directory_listing(server) -> None:
    port, _ = server
    for path in ("/api/reports/missing.md", "/api/reports/", "/api/reports/."):
        status, _, body = _get(port, path)
        assert status == 404, path
        assert b"status-report" not in body


def test_reports_stay_behind_the_existing_host_check(server) -> None:
    port, _ = server
    status, _, body = _get(port, "/api/reports", host="evil.example.com")
    assert status == 403
    assert b"status-report" not in body
