from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

POWERSHELL = r"""
$ErrorActionPreference = 'Stop'
$def = Get-MpComputerStatus
$threats = @(Get-MpThreatDetection | Select-Object -First 50 ThreatID,InitialDetectionTime,LastThreatStatusChangeTime,ThreatStatusID,ActionSuccess,Resources)
$firewall = @(Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction)
$startup = @(Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location,User)
$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Select-Object -First 100 LocalAddress,LocalPort,OwningProcess)
$processes = @(Get-Process | Sort-Object CPU -Descending | Select-Object -First 30 ProcessName,Id,CPU,Path)
$result = [ordered]@{
  collected_at = (Get-Date).ToString('o')
  computer = $env:COMPUTERNAME
  defender = [ordered]@{
    service_enabled = [bool]$def.AMServiceEnabled
    antivirus_enabled = [bool]$def.AntivirusEnabled
    realtime_protection = [bool]$def.RealTimeProtectionEnabled
    behavior_monitor = [bool]$def.BehaviorMonitorEnabled
    signatures_updated = if ($def.AntivirusSignatureLastUpdated) { $def.AntivirusSignatureLastUpdated.ToString('o') } else { $null }
    quick_scan_age_days = $def.QuickScanAge
    full_scan_age_days = $def.FullScanAge
  }
  threat_detections = $threats
  firewall_profiles = $firewall
  startup_entries = $startup
  listening_tcp_ports = $listeners
  top_processes_by_cpu = $processes
}
$result | ConvertTo-Json -Depth 6 -Compress
"""

def audit_pc() -> dict[str, Any]:
    """Collect a bounded, read-only Windows security posture report."""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned", "-Command", POWERSHELL],
        capture_output=True, text=True, timeout=90, check=False, shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout)[-4000:] or "Windows security audit failed.")
    output = completed.stdout.strip()
    start = output.find("{")
    if start < 0:
        raise RuntimeError("Windows security audit returned no JSON report.")
    try:
        report = json.loads(output[start:])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Windows security audit returned invalid JSON.") from exc
    report["mode"] = "read_only_windows_security_posture"
    report["limitations"] = [
        "This is a posture and inventory audit, not a malware scan of every file.",
        "Defender threat history can include already-remediated detections.",
        "Listening ports and startup entries are inventory data, not proof of malicious activity.",
        "No files, settings, processes, or network connections were changed.",
    ]
    report_dir = Path(__file__).resolve().parents[4] / "data" / "pc-security"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "latest.json"
    temp_path = report_dir / "latest.json.tmp"
    temp_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    temp_path.replace(report_path)
    report["report_path"] = str(report_path)
    return cast(dict[str, Any], report)


def start_defender_quick_scan() -> dict[str, Any]:
    """Request a Microsoft Defender quick scan; does not quarantine or delete files."""
    command = "Start-MpScan -ScanType QuickScan; Get-MpComputerStatus | Select-Object QuickScanStartTime,QuickScanEndTime,QuickScanAge | ConvertTo-Json -Compress"
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned", "-Command", command],
        capture_output=True, text=True, timeout=60, check=False, shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout)[-4000:] or "Defender quick scan could not be started.")
    return {"started": True, "output": completed.stdout.strip()[-2000:], "engine": "Microsoft Defender"}
