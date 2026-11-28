"""Read-only Windows security posture audit through Microsoft Defender and WMI.

Ported from the remote ``jarvis.skills.pc_security``. Everything here is
inventory: Defender status, recent threat detections, firewall profiles, startup
entries, listening TCP ports and the busiest processes. Nothing is changed,
quarantined or terminated, and the audit's own limitations say so in the report.

``start_defender_quick_scan`` is the one action, and it is approval-gated at the
registry because starting a scan uses real machine resources.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

from ..security.permissions import PermissionTier
from .manifest import ToolManifest
from .registry import ToolContext, ToolRegistry, ToolResult

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

#: Default report location when a caller supplies none: <repo>/data/pc-security.
DEFAULT_REPORT_DIR = Path(__file__).resolve().parents[4] / "data" / "pc-security"


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("The PC security audit is Windows-only.")


def audit_pc(report_dir: str | Path | None = None) -> dict[str, Any]:
    """Collect a bounded, read-only Windows security posture report."""
    _require_windows()
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
    target = Path(report_dir) if report_dir is not None else DEFAULT_REPORT_DIR
    target.mkdir(parents=True, exist_ok=True)
    report_path = target / "latest.json"
    temp_path = target / "latest.json.tmp"
    temp_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    temp_path.replace(report_path)
    report["report_path"] = str(report_path)
    return cast(dict[str, Any], report)


def start_defender_quick_scan() -> dict[str, Any]:
    """Request a Microsoft Defender quick scan; does not quarantine or delete files."""
    _require_windows()
    command = "Start-MpScan -ScanType QuickScan; Get-MpComputerStatus | Select-Object QuickScanStartTime,QuickScanEndTime,QuickScanAge | ConvertTo-Json -Compress"
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned", "-Command", command],
        capture_output=True, text=True, timeout=60, check=False, shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout)[-4000:] or "Defender quick scan could not be started.")
    return {"started": True, "output": completed.stdout.strip()[-2000:], "engine": "Microsoft Defender"}


def _report_dir(context: ToolContext) -> Path:
    return Path(context.settings.data_dir) / "pc-security"


async def _pc_audit(args: dict[str, Any], context: ToolContext) -> ToolResult:
    try:
        report = await asyncio.to_thread(audit_pc, _report_dir(context))
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    return ToolResult(
        ok=True,
        output={
            "report_path": report["report_path"],
            "computer": report.get("computer"),
            "collected_at": report.get("collected_at"),
            "defender": report.get("defender"),
            "threat_detections": report.get("threat_detections"),
            "firewall_profiles": report.get("firewall_profiles"),
            "startup_entries": (report.get("startup_entries") or [])[:25],
            "listening_tcp_ports": (report.get("listening_tcp_ports") or [])[:50],
            "top_processes_by_cpu": (report.get("top_processes_by_cpu") or [])[:15],
            "mode": report["mode"],
            "limitations": report["limitations"],
        },
    )


async def _defender_quick_scan(args: dict[str, Any], context: ToolContext) -> ToolResult:
    try:
        result = await asyncio.to_thread(start_defender_quick_scan)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    return ToolResult(ok=True, output=result)


def register_pc_security_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolManifest(
            name="security.pc_audit",
            description=(
                "Audit this Windows PC's defensive posture, read-only: Defender status "
                "and signature age, recent threat detections, firewall profiles, startup "
                "entries, listening TCP ports and the busiest processes."
            ),
            permission=PermissionTier.READ_ONLY,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            timeout_s=120,
            tags=["security", "windows", "defender", "audit"],
        ),
        _pc_audit,
    )
    registry.register(
        ToolManifest(
            name="security.defender_scan",
            description=(
                "Ask Microsoft Defender to run a quick scan and report the scan window. "
                "Does not quarantine or delete anything; approval-gated because it uses "
                "real machine resources."
            ),
            permission=PermissionTier.CONFIRM,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            timeout_s=90,
            tags=["security", "windows", "defender"],
        ),
        _defender_quick_scan,
    )


__all__ = [
    "DEFAULT_REPORT_DIR",
    "audit_pc",
    "register_pc_security_tools",
    "start_defender_quick_scan",
]
