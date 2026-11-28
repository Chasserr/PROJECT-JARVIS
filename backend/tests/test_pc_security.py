"""PC security audit: report parsing against a replaced PowerShell boundary.

The audit shells out to PowerShell, so these tests replace that boundary and
assert how the report is parsed, bounded and written. Nothing here reads this
machine's Defender state.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from jarvis.tools import pc_security

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="Windows Defender and WMI audit only"
)


def test_audit_pc_parses_read_only_report(monkeypatch, tmp_path):
    payload = {
        "computer": "TEST-PC",
        "defender": {"realtime_protection": True},
        "threat_detections": [],
        "firewall_profiles": [{"Name": "Public", "Enabled": True}],
    }

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, json.dumps(payload), "")

    monkeypatch.setattr(pc_security.subprocess, "run", fake_run)
    report = pc_security.audit_pc(tmp_path)
    assert report["computer"] == "TEST-PC"
    assert report["defender"]["realtime_protection"] is True
    assert report["mode"] == "read_only_windows_security_posture"
    assert report["limitations"]
    assert report["report_path"] == str(tmp_path / "latest.json")
    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["computer"] == "TEST-PC"


def test_audit_pc_rejects_failed_powershell(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, "", "Access denied")

    monkeypatch.setattr(pc_security.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="Access denied"):
        pc_security.audit_pc(tmp_path)


def test_audit_pc_rejects_output_without_json(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, "no report here", "")

    monkeypatch.setattr(pc_security.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="no JSON report"):
        pc_security.audit_pc(tmp_path)


def test_quick_scan_reports_engine_and_start(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, '{"QuickScanAge":0}', "")

    monkeypatch.setattr(pc_security.subprocess, "run", fake_run)
    result = pc_security.start_defender_quick_scan()
    assert result["started"] is True
    assert result["engine"] == "Microsoft Defender"
