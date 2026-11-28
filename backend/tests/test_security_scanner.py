"""Static source scanner: real reports over real temp trees, no network.

Every scan here writes into a temporary project, so the assertions cover what
the scanner reports (rules, severities, redaction, bounds) rather than anything
about this machine's source.
"""

from __future__ import annotations

import json

import pytest

from jarvis.tools.security_scanner import report_dir_for, scan_project


def test_scanner_finds_secrets_and_redacts_values(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    sample_assignment = 'API_KEY = "' + "super-" + "secret-" + "value-123456" + '"\n'
    (root / "settings.py").write_text(sample_assignment, encoding="utf-8")
    report = scan_project(root, root / "data" / "security-reports")
    assert report["summary"]["high"] == 1
    finding = report["findings"][0]
    assert finding["rule_id"] == "SEC005"
    assert "super-secret-value" not in json.dumps(report)
    assert (root / "data" / "security-reports" / "latest.json").exists()


def test_scanner_finds_unsafe_python_calls(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "unsafe.py").write_text(
        "import subprocess\n"
        "import pickle\n"
        "subprocess.run('echo unsafe', shell=True)\n"
        "pickle.loads(payload)\n"
        "eval(user_input)\n",
        encoding="utf-8",
    )
    report = scan_project(root, root / "reports")
    rule_ids = {item["rule_id"] for item in report["findings"]}
    assert {"CODE001", "CODE005", "CODE007"} <= rule_ids


def test_scanner_ignores_placeholders_and_excluded_directories(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / ".env.example").write_text(
        'API_KEY="your_api_key_here"\nPASSWORD="change-me-now"\n',
        encoding="utf-8",
    )
    cache = root / "node_modules"
    cache.mkdir()
    (cache / "leaked.py").write_text(
        'TOKEN="real-secret-token-123456789"\n', encoding="utf-8"
    )
    report = scan_project(root, root / "reports")
    assert report["findings"] == []
    assert report["scanned_files"] == 1


def test_scanner_rejects_report_path_outside_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    with pytest.raises(ValueError, match="inside the project root"):
        scan_project(root, outside)


def test_scanner_reports_bounded_read_only_scope(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("hello", encoding="utf-8")
    report = scan_project(root, root / "reports")
    assert report["mode"] == "read_only_local_static_scan"
    assert report["scanned_files"] == 1
    assert report["summary"]["total_findings"] == 0
    assert report["limitations"]


def test_report_directory_falls_back_inside_the_scanned_tree(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    inside = root / "reports"
    assert report_dir_for(root, inside) == inside.resolve()
    # A data directory outside the scanned tree cannot be used: the scanner
    # would be writing outside the only tree it is allowed to touch.
    assert report_dir_for(root, tmp_path / "data") == root.resolve() / "data" / "security-reports"


def test_scanner_survives_an_unreadable_entry(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "ok.md").write_text("hello", encoding="utf-8")
    (root / "binary.dat").write_bytes(b"\x00\x01\x02")
    report = scan_project(root, root / "reports")
    # A non-text suffix is not scanned at all; the walk must not crash.
    assert report["scanned_files"] == 1
    assert report["summary"]["total_findings"] == 0
