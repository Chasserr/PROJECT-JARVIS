from __future__ import annotations

import json

from jarvis.skills.security_scanner import scan_project


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
    try:
        scan_project(root, outside)
    except ValueError as exc:
        assert "inside the project root" in str(exc)
    else:
        raise AssertionError("outside report path should be rejected")


def test_scanner_reports_bounded_read_only_scope(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("hello", encoding="utf-8")
    report = scan_project(root, root / "reports")
    assert report["mode"] == "read_only_local_static_scan"
    assert report["scanned_files"] == 1
    assert report["summary"]["total_findings"] == 0
    assert report["limitations"]
