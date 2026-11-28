"""BugHunter integration: the real library, its confinement rules and inputs."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.tools import bughunter

requires_library = pytest.mark.skipif(
    not Path(bughunter.BUGHUNTER_ROOT).is_dir(),
    reason=f"Claude-BugHunter is not installed at {bughunter.BUGHUNTER_ROOT}",
)


@requires_library
def test_bughunter_capabilities_are_discoverable():
    result = bughunter.capabilities()
    assert result["available"] is True
    assert result["skill_count"] >= 70
    assert "recon" in result["commands"]
    assert "hunt" in result["commands"]
    assert "classify" in result["cli_operations"]
    assert result["active_hunt_runner"] == "not exposed to autonomous JARVIS execution"


def test_bughunter_url_classifier_rejects_non_http_urls():
    with pytest.raises(ValueError, match="http:// or https://"):
        bughunter.classify_url("file:///etc/passwd")


def test_bughunter_url_classifier_rejects_oversized_urls():
    with pytest.raises(ValueError, match="2000 characters"):
        bughunter.classify_url("https://example.com/" + "a" * 2_000)


@requires_library
def test_bughunter_skill_guides_are_read_from_the_installed_library():
    result = bughunter.read_skill("hunt-idor")
    assert result["skill"] == "hunt-idor"
    assert "IDOR" in result["content"].upper()
    assert result["path"].endswith("hunt-idor\\SKILL.md")


@requires_library
def test_bughunter_skill_reader_rejects_unknown_names():
    with pytest.raises(ValueError, match="Unknown BugHunter skill"):
        bughunter.read_skill("../../outside")


def test_bughunter_finding_path_is_confined_to_findings_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(bughunter, "FINDINGS_ROOT", tmp_path)
    (tmp_path / "valid.md").write_text("# Finding", encoding="utf-8")
    assert bughunter._finding_path("valid.md") == tmp_path / "valid.md"
    with pytest.raises(ValueError, match="only a finding filename"):
        bughunter._finding_path("..\\outside.md")
    with pytest.raises(ValueError, match="must already exist"):
        bughunter._finding_path("missing.md")


def test_report_platforms_are_validated_before_any_cli_call(tmp_path):
    (tmp_path / "finding.md").write_text("# Finding", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported report platform"):
        bughunter.draft_report(
            "finding.md",
            "twitter",
            findings_root=tmp_path,
            drafts_root=tmp_path / "reports",
        )
