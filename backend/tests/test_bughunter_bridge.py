from __future__ import annotations

from pathlib import Path

from jarvis.skills import bughunter


def test_bridge_resolves_repository_root_not_backend_directory():
    expected_root = Path(__file__).resolve().parents[2]
    assert bughunter.PROJECT_ROOT == expected_root
    assert bughunter.REPORT_ROOT == expected_root / "data" / "bughunter"


def test_capabilities_exposes_installed_skill_bundle():
    result = bughunter.capabilities()
    assert result["available"] is True
    assert result["skill_count"] >= 80
    assert "hunt-xss" in result["skills"]
    assert "classify" in result["cli_operations"]
    assert result["active_hunt_runner"] == "not exposed to autonomous JARVIS execution"


def test_url_classification_is_local_and_returns_skill_guidance():
    result = bughunter.classify_url("https://example.invalid/api/v1/users")
    assert result["return_code"] == 0
    assert "hunt-api-misconfig" in result["stdout"]
    assert result["stderr"] == ""


def test_classify_rejects_non_http_urls():
    try:
        bughunter.classify_url("file:///C:/Windows/win.ini")
    except ValueError as exc:
        assert "http:// or https://" in str(exc)
    else:
        raise AssertionError("non-HTTP URL should be rejected")
