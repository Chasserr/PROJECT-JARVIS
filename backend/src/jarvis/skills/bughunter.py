from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from jarvis.skills.security_scanner import scan_project

PROJECT_ROOT = Path(__file__).resolve().parents[4]
BUGHUNTER_ROOT = Path(r"E:\AI-TOOLS\Claude-BugHunter")
CLI_PATH = BUGHUNTER_ROOT / "scripts" / "cbh.py"
REPORT_ROOT = PROJECT_ROOT / "data" / "bughunter"
FINDINGS_ROOT = REPORT_ROOT / "findings"
DRAFTS_ROOT = REPORT_ROOT / "reports"
PLATFORMS = {"h1", "hackerone", "bugcrowd", "intigriti", "immunefi"}


class BugHunterUnavailable(RuntimeError):
    pass


def _run_cli(*arguments: str, timeout: int = 90) -> dict[str, Any]:
    if not CLI_PATH.is_file():
        raise BugHunterUnavailable(f"BugHunter CLI not found at {CLI_PATH}")
    completed = subprocess.run(
        [sys.executable, str(CLI_PATH), *arguments],
        cwd=str(BUGHUNTER_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
    return {
        "returncode": completed.returncode,
        "return_code": completed.returncode,
        "stdout": completed.stdout[-20_000:],
        "stderr": completed.stderr[-8_000:],
    }


def capabilities() -> dict[str, Any]:
    if not BUGHUNTER_ROOT.is_dir():
        raise BugHunterUnavailable(f"BugHunter repository not found at {BUGHUNTER_ROOT}")
    skill_root = BUGHUNTER_ROOT / "skills"
    command_root = BUGHUNTER_ROOT / "commands"
    skill_names = sorted(path.name for path in skill_root.iterdir() if path.is_dir())
    command_names = sorted(path.stem for path in command_root.glob("*.md"))
    return {
        "available": True,
        "repository": str(BUGHUNTER_ROOT),
        "version": "2.1.0",
        "skill_count": len(skill_names),
        "skills": skill_names,
        "commands": command_names,
        "cli_operations": ["recon", "surface", "classify", "triage", "report", "scope"],
        "active_hunt_runner": "not exposed to autonomous JARVIS execution",
    }


def read_skill(skill_name: str) -> dict[str, Any]:
    available = set(capabilities()["skills"])
    if skill_name not in available:
        raise ValueError("Unknown BugHunter skill name.")
    path = (BUGHUNTER_ROOT / "skills" / skill_name / "SKILL.md").resolve()
    if path.parent.parent != (BUGHUNTER_ROOT / "skills").resolve() or not path.is_file():
        raise ValueError("BugHunter skill file is missing or outside the skill library.")
    text = path.read_text(encoding="utf-8")
    return {"skill": skill_name, "path": str(path), "content": text[:16_000],
            "truncated": len(text) > 16_000}


def classify_url(url: str) -> dict[str, Any]:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("URL must begin with http:// or https://")
    if len(url) > 2_000:
        raise ValueError("URL exceeds 2000 characters")
    return _run_cli("classify", url)


def _finding_path(finding_name: str) -> Path:
    if not isinstance(finding_name, str) or Path(finding_name).name != finding_name:
        raise ValueError("Provide only a finding filename, not a path.")
    if not finding_name.lower().endswith(".md"):
        raise ValueError("Finding files must use the .md extension.")
    root = FINDINGS_ROOT.resolve()
    path = (root / finding_name).resolve()
    if path.parent != root or not path.is_file():
        raise ValueError("Finding file must already exist inside JARVIS data/bughunter/findings.")
    return path


def surface_local() -> dict[str, Any]:
    manifest = REPORT_ROOT / "recon" / "localhost" / "manifest.json"
    if not manifest.is_file():
        raise ValueError("Run the local BugHunter audit before ranking its attack surface.")
    return _run_cli("surface", "localhost", "--manifest", str(manifest))


def triage_finding(finding_name: str) -> dict[str, Any]:
    path = _finding_path(finding_name)
    return _run_cli("triage", str(path))


def draft_report(finding_name: str, platform: str) -> dict[str, Any]:
    path = _finding_path(finding_name)
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported report platform. Choose one of: {', '.join(sorted(PLATFORMS))}.")
    DRAFTS_ROOT.mkdir(parents=True, exist_ok=True)
    output = DRAFTS_ROOT / f"{path.stem}-{platform}-draft.md"
    if output.exists():
        raise ValueError("A report draft with that name already exists; refusing to overwrite it.")
    result = _run_cli("report", str(path), "--platform", platform, "--out", str(output))
    result["draft_path"] = str(output) if output.is_file() else None
    result["output_exists"] = output.is_file()
    return result


def _extract_counts(stdout: str) -> dict[str, int]:
    labels = {"subdomains": "Subdomains", "resolved": "Resolved", "http_live": "HTTP-live"}
    counts: dict[str, int] = {}
    for key, label in labels.items():
        match = re.search(rf"{re.escape(label)}:\s*(\d+)", stdout)
        if match:
            counts[key] = int(match.group(1))
    return counts


def _classification_summary(result: dict[str, Any]) -> dict[str, Any]:
    names = sorted(set(re.findall(
        r"skills[\\/](hunt-[a-z0-9-]+)[\\/]SKILL\.md", result.get("stdout", ""), re.IGNORECASE
    )))
    return {"returncode": result["returncode"], "matched_skills": names}


def local_audit() -> dict[str, Any]:
    """Run read-only source checks and classify JARVIS routes without network access."""
    if not BUGHUNTER_ROOT.is_dir():
        raise BugHunterUnavailable(f"BugHunter repository not found at {BUGHUNTER_ROOT}")
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    static_scan = scan_project(PROJECT_ROOT, REPORT_ROOT / "security-reports")
    routes = {
        "health": "http://localhost/api/v1/health",
        "skills": "http://localhost/api/v1/skills",
        "security_status": "http://localhost/api/v1/security/status",
    }
    classifications = {name: _run_cli("classify", url, timeout=20)
                        for name, url in routes.items()}
    ranked = []
    for name, url in routes.items():
        output = classifications[name].get("stdout", "")
        matched = sorted(set(re.findall(r"\b(hunt-[a-z0-9-]+)\b", output, re.IGNORECASE)))
        ranked.append({
            "url": url,
            "host": "localhost",
            "bug_classes": matched,
            "priority": "P2",
            "rationale": "Local route pattern classification only; no vulnerability has been verified.",
        })
    manifest = {
        "schema_version": "1.0",
        "target": "localhost",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(timespec="seconds"),
        "producers": ["jarvis-bughunter-local/1.0"],
        "counts": {"subdomains": 1, "resolved": 1, "live": len(routes)},
        "assets": [{"host": "localhost", "ips": ["127.0.0.1"], "url": url,
                    "status": None, "server": "", "title": name,
                    "tech": [], "source": "local-route-inventory"}
                   for name, url in routes.items()],
        "ranked_surface": ranked,
        "secrets": [],
        "identity_fabric": {},
    }
    recon_dir = REPORT_ROOT / "recon" / "localhost"
    recon_dir.mkdir(parents=True, exist_ok=True)
    (recon_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    surface = _run_cli("surface", "localhost", "--manifest",
                       str(recon_dir / "manifest.json"), timeout=20)
    log_lines = []
    for name, result in classifications.items():
        log_lines.extend([f"=== {name.upper()} ===", result.get("stdout", ""),
                          result.get("stderr", "")])
    log_lines.extend(["=== LOCAL SURFACE ===", surface.get("stdout", ""),
                      surface.get("stderr", "")])
    log_path = REPORT_ROOT / "latest-local-audit.log"
    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    result = {
        "tool": "Claude-BugHunter",
        "workflow": "JARVIS-local-read-only-audit",
        "scope": str(PROJECT_ROOT),
        "jarvis_static_scan": {
            "scan_id": static_scan["scan_id"],
            "scanned_files": static_scan["scanned_files"],
            "summary": static_scan["summary"],
            "report": str(REPORT_ROOT / "security-reports" / "latest.json"),
        },
        "bughunter_api_classifications": {
            name: {"return_code": item["return_code"],
                   "matched_skills": sorted(set(re.findall(
                       r"(hunt-[a-z0-9-]+)",item.get("stdout", ""), re.IGNORECASE
                   )))}
            for name, item in classifications.items()
        },
        "bughunter_surface": {"return_code": surface["return_code"],
                              "summary": surface.get("stdout", "")[-3000:]},
        "report_directory": str(REPORT_ROOT),
        "log_file": str(log_path),
        "limitations": [
            "Static source checks and URL pattern classification only; not a penetration test.",
            "No network requests, external target scans, exploit attempts, credential attacks, or source modifications.",
            "Secret values are redacted by the static scanner.",
            "The separate engine.py active hunt runner is not invoked.",
        ],
    }
    (REPORT_ROOT / "latest-local-audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result
