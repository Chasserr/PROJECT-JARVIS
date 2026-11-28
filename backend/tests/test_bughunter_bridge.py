"""BugHunter bridge: path resolution, capabilities and URL classification.

The bridge reads an external library, so the library-dependent assertions skip
when it is not installed instead of passing on a guess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.tools import bughunter

requires_library = pytest.mark.skipif(
    not Path(bughunter.BUGHUNTER_ROOT).is_dir(),
    reason=f"Claude-BugHunter is not installed at {bughunter.BUGHUNTER_ROOT}",
)


def test_bridge_resolves_repository_root_not_backend_directory():
    expected_root = Path(__file__).resolve().parents[2]
    assert expected_root == bughunter.PROJECT_ROOT
    assert expected_root / "data" / "bughunter" == bughunter.REPORT_ROOT


@requires_library
def test_capabilities_exposes_installed_skill_bundle():
    result = bughunter.capabilities()
    assert result["available"] is True
    assert result["skill_count"] >= 80
    assert "hunt-xss" in result["skills"]
    assert "classify" in result["cli_operations"]
    assert result["active_hunt_runner"] == "not exposed to autonomous JARVIS execution"


@requires_library
def test_url_classification_is_local_and_returns_skill_guidance():
    result = bughunter.classify_url("https://example.invalid/api/v1/users")
    assert result["return_code"] == 0
    assert "hunt-api-misconfig" in result["stdout"]
    assert result["stderr"] == ""


def test_classify_rejects_non_http_urls():
    with pytest.raises(ValueError, match="http:// or https://"):
        bughunter.classify_url("file:///C:/Windows/win.ini")


def test_missing_library_is_reported_as_unavailable(tmp_path):
    with pytest.raises(bughunter.BugHunterUnavailable, match="not found"):
        bughunter.capabilities(tmp_path / "nowhere")
