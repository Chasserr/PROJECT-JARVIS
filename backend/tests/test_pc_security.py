from __future__ import annotations

import json
import subprocess

from jarvis.skills import pc_security


def test_audit_pc_parses_read_only_report(monkeypatch):
    payload = {
        "computer": "TEST-PC",
        "defender": {"realtime_protection": True},
        "threat_detections": [],
        "firewall_profiles": [{"Name": "Public", "Enabled": True}],
    }

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, json.dumps(payload), "")

    monkeypatch.setattr(pc_security.subprocess, "run", fake_run)
    report = pc_security.audit_pc()
    assert report["computer"] == "TEST-PC"
    assert report["defender"]["realtime_protection"] is True
    assert report["mode"] == "read_only_windows_security_posture"
    assert report["limitations"]


def test_audit_pc_rejects_failed_powershell(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, "", "Access denied")

    monkeypatch.setattr(pc_security.subprocess, "run", fake_run)
    try:
        pc_security.audit_pc()
    except RuntimeError as exc:
        assert "Access denied" in str(exc)
    else:
        raise AssertionError("failed PowerShell command must raise")


def test_quick_scan_reports_engine_and_start(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, '{"QuickScanAge":0}', "")

    monkeypatch.setattr(pc_security.subprocess, "run", fake_run)
    result = pc_security.start_defender_quick_scan()
    assert result["started"] is True
    assert result["engine"] == "Microsoft Defender"
