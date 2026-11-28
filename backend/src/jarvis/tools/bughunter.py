"""Bridge to the local Claude-BugHunter skill library, as defensive tooling.

Ported from the remote ``jarvis.skills.bughunter`` onto the local tool
architecture. The bridge only ever reads the library and classifies URLs that
were already in scope: it exposes skill guides, URL-to-bug-class classification,
triage of an existing finding file and report drafting. The library's own active
hunt engine (``engine.py``) is deliberately not reachable from a tool call.

Every path is confined: findings must be a bare ``.md`` filename inside the
configured findings directory, drafts are never overwritten, and a URL has to be
http(s) and under 2000 characters. The library location is
``JARVIS_BUGHUNTER_ROOT`` (or ``settings.bughunter_root``), because a tool must
not assume where another project was installed.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..security.permissions import PermissionTier
from .manifest import ToolManifest
from .registry import ToolContext, ToolRegistry, ToolResult
from .security_scanner import report_dir_for, scan_project

PROJECT_ROOT = Path(__file__).resolve().parents[4]
#: Installed library location; override with JARVIS_BUGHUNTER_ROOT.
DEFAULT_BUGHUNTER_ROOT = Path(
    os.environ.get("JARVIS_BUGHUNTER_ROOT") or r"E:\AI-TOOLS\Claude-BugHunter"
)
BUGHUNTER_ROOT = DEFAULT_BUGHUNTER_ROOT
REPORT_ROOT = PROJECT_ROOT / "data" / "bughunter"
FINDINGS_ROOT = REPORT_ROOT / "findings"
DRAFTS_ROOT = REPORT_ROOT / "reports"
PLATFORMS = {"h1", "hackerone", "bugcrowd", "intigriti", "immunefi"}


class BugHunterUnavailable(RuntimeError):
    """The Claude-BugHunter library is not installed where we looked."""


def _library(root: str | Path | None = None) -> Path:
    return Path(root) if root is not None else BUGHUNTER_ROOT


def _cli_path(root: str | Path | None = None) -> Path:
    return _library(root) / "scripts" / "cbh.py"


def _run_cli(
    *arguments: str, timeout: int = 90, root: str | Path | None = None
) -> dict[str, Any]:
    library = _library(root)
    cli = _cli_path(root)
    if not cli.is_file():
        raise BugHunterUnavailable(f"BugHunter CLI not found at {cli}")
    completed = subprocess.run(
        [sys.executable, str(cli), *arguments],
        cwd=str(library),
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


def capabilities(root: str | Path | None = None) -> dict[str, Any]:
    library = _library(root)
    if not library.is_dir():
        raise BugHunterUnavailable(f"BugHunter repository not found at {library}")
    skill_root = library / "skills"
    command_root = library / "commands"
    skill_names = sorted(path.name for path in skill_root.iterdir() if path.is_dir())
    command_names = sorted(path.stem for path in command_root.glob("*.md"))
    return {
        "available": True,
        "repository": str(library),
        "version": "2.1.0",
        "skill_count": len(skill_names),
        "skills": skill_names,
        "commands": command_names,
        "cli_operations": ["recon", "surface", "classify", "triage", "report", "scope"],
        "active_hunt_runner": "not exposed to autonomous JARVIS execution",
    }


def read_skill(skill_name: str, root: str | Path | None = None) -> dict[str, Any]:
    available = set(capabilities(root)["skills"])
    if skill_name not in available:
        raise ValueError("Unknown BugHunter skill name.")
    library = _library(root)
    path = (library / "skills" / skill_name / "SKILL.md").resolve()
    if path.parent.parent != (library / "skills").resolve() or not path.is_file():
        raise ValueError("BugHunter skill file is missing or outside the skill library.")
    text = path.read_text(encoding="utf-8")
    return {
        "skill": skill_name,
        "path": str(path),
        "content": text[:16_000],
        "truncated": len(text) > 16_000,
    }


def classify_url(url: str, root: str | Path | None = None) -> dict[str, Any]:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("URL must begin with http:// or https://")
    if len(url) > 2_000:
        raise ValueError("URL exceeds 2000 characters")
    return _run_cli("classify", url, root=root)


def _finding_path(finding_name: str, findings_root: str | Path | None = None) -> Path:
    if not isinstance(finding_name, str) or Path(finding_name).name != finding_name:
        raise ValueError("Provide only a finding filename, not a path.")
    if not finding_name.lower().endswith(".md"):
        raise ValueError("Finding files must use the .md extension.")
    root = Path(findings_root if findings_root is not None else FINDINGS_ROOT).resolve()
    path = (root / finding_name).resolve()
    if path.parent != root or not path.is_file():
        raise ValueError("Finding file must already exist inside JARVIS data/bughunter/findings.")
    return path


def surface_local(
    *, root: str | Path | None = None, report_root: str | Path | None = None
) -> dict[str, Any]:
    target = Path(report_root if report_root is not None else REPORT_ROOT)
    manifest = target / "recon" / "localhost" / "manifest.json"
    if not manifest.is_file():
        raise ValueError("Run the local BugHunter audit before ranking its attack surface.")
    return _run_cli("surface", "localhost", "--manifest", str(manifest), root=root)


def triage_finding(
    finding_name: str, *, root: str | Path | None = None, findings_root: str | Path | None = None
) -> dict[str, Any]:
    path = _finding_path(finding_name, findings_root)
    return _run_cli("triage", str(path), root=root)


def draft_report(
    finding_name: str,
    platform: str,
    *,
    root: str | Path | None = None,
    findings_root: str | Path | None = None,
    drafts_root: str | Path | None = None,
) -> dict[str, Any]:
    path = _finding_path(finding_name, findings_root)
    if platform not in PLATFORMS:
        raise ValueError(
            f"Unsupported report platform. Choose one of: {', '.join(sorted(PLATFORMS))}."
        )
    target = Path(drafts_root if drafts_root is not None else DRAFTS_ROOT)
    target.mkdir(parents=True, exist_ok=True)
    output = target / f"{path.stem}-{platform}-draft.md"
    if output.exists():
        raise ValueError("A report draft with that name already exists; refusing to overwrite it.")
    result = _run_cli("report", str(path), "--platform", platform, "--out", str(output), root=root)
    result["draft_path"] = str(output) if output.is_file() else None
    result["output_exists"] = output.is_file()
    return result


def local_audit(
    *,
    root: str | Path | None = None,
    report_root: str | Path | None = None,
    findings_root: str | Path | None = None,
    drafts_root: str | Path | None = None,
    scan_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run read-only source checks and classify JARVIS routes without network access."""
    library = _library(root)
    if not library.is_dir():
        raise BugHunterUnavailable(f"BugHunter repository not found at {library}")
    reports = Path(report_root if report_root is not None else REPORT_ROOT)
    reports.mkdir(parents=True, exist_ok=True)
    project = Path(scan_root if scan_root is not None else PROJECT_ROOT).resolve()
    static_scan = scan_project(project, report_dir_for(project, reports / "security-reports"))
    routes = {
        "health": "http://localhost/api/v1/health",
        "skills": "http://localhost/api/v1/skills",
        "security_status": "http://localhost/api/v1/security/status",
    }
    classifications = {
        name: _run_cli("classify", url, timeout=20, root=root) for name, url in routes.items()
    }
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
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
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
    recon_dir = reports / "recon" / "localhost"
    recon_dir.mkdir(parents=True, exist_ok=True)
    (recon_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    surface = _run_cli(
        "surface", "localhost", "--manifest", str(recon_dir / "manifest.json"), timeout=20, root=root
    )
    log_lines = []
    for name, result in classifications.items():
        log_lines.extend([f"=== {name.upper()} ===", result.get("stdout", ""),
                          result.get("stderr", "")])
    log_lines.extend(["=== LOCAL SURFACE ===", surface.get("stdout", ""),
                      surface.get("stderr", "")])
    log_path = reports / "latest-local-audit.log"
    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    result = {
        "tool": "Claude-BugHunter",
        "workflow": "JARVIS-local-read-only-audit",
        "returncode": 0 if surface["return_code"] == 0 and all(
            item["return_code"] == 0 for item in classifications.values()
        ) else 1,
        "output_exists": True,
        "scope": str(project),
        "jarvis_static_scan": {
            "scan_id": static_scan["scan_id"],
            "scanned_files": static_scan["scanned_files"],
            "summary": static_scan["summary"],
            "report": str(report_dir_for(project, reports / "security-reports") / "latest.json"),
        },
        "bughunter_api_classifications": {
            name: {"return_code": item["return_code"],
                   "matched_skills": sorted(set(re.findall(
                       r"(hunt-[a-z0-9-]+)", item.get("stdout", ""), re.IGNORECASE
                   )))}
            for name, item in classifications.items()
        },
        "bughunter_surface": {"return_code": surface["return_code"],
                              "summary": surface.get("stdout", "")[-3000:]},
        "report_directory": str(reports),
        "log_file": str(log_path),
        "limitations": [
            "Static source checks and URL pattern classification only; not a penetration test.",
            "No network requests, external target scans, exploit attempts, credential attacks, or source modifications.",
            "Secret values are redacted by the static scanner.",
            "The separate engine.py active hunt runner is not invoked.",
        ],
    }
    (reports / "latest-local-audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


# ------------------------------------------------------------------- tools


def _library_root(context: ToolContext) -> Path | None:
    configured = context.settings.bughunter_root
    return Path(configured) if configured else None


def _report_root(context: ToolContext) -> Path:
    return Path(context.settings.data_dir) / "bughunter"


def _paths(context: ToolContext) -> dict[str, Any]:
    reports = _report_root(context)
    return {
        "root": _library_root(context),
        "report_root": reports,
        "findings_root": reports / "findings",
        "drafts_root": reports / "reports",
    }


def _guarded(action, *args, **kwargs) -> ToolResult:
    try:
        return ToolResult(ok=True, output=action(*args, **kwargs))
    except (BugHunterUnavailable, ValueError, OSError, subprocess.SubprocessError) as exc:
        return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")


async def _bughunter_status(args: dict[str, Any], context: ToolContext) -> ToolResult:
    return _guarded(capabilities, _library_root(context))


async def _bughunter_skill(args: dict[str, Any], context: ToolContext) -> ToolResult:
    return _guarded(read_skill, args["skill"], _library_root(context))


async def _bughunter_classify(args: dict[str, Any], context: ToolContext) -> ToolResult:
    return _guarded(classify_url, args["url"], _library_root(context))


async def _bughunter_triage(args: dict[str, Any], context: ToolContext) -> ToolResult:
    paths = _paths(context)
    return _guarded(
        triage_finding,
        args["finding"],
        root=paths["root"],
        findings_root=paths["findings_root"],
    )


async def _bughunter_report(args: dict[str, Any], context: ToolContext) -> ToolResult:
    paths = _paths(context)
    return _guarded(
        draft_report,
        args["finding"],
        args["platform"],
        root=paths["root"],
        findings_root=paths["findings_root"],
        drafts_root=paths["drafts_root"],
    )


async def _bughunter_audit(args: dict[str, Any], context: ToolContext) -> ToolResult:
    paths = _paths(context)
    scan_root = context.settings.project_root or PROJECT_ROOT
    try:
        result = await asyncio.to_thread(
            local_audit,
            root=paths["root"],
            report_root=paths["report_root"],
            scan_root=scan_root,
        )
    except (BugHunterUnavailable, ValueError, OSError, subprocess.SubprocessError) as exc:
        return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    return ToolResult(ok=True, output=result)


def register_bughunter_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolManifest(
            name="security.bughunter_status",
            description=(
                "List the installed Claude-BugHunter skills, commands and CLI operations, "
                "or report that the library is not installed."
            ),
            permission=PermissionTier.READ_ONLY,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            timeout_s=30,
            tags=["security", "bughunter", "skills"],
        ),
        _bughunter_status,
    )
    registry.register(
        ToolManifest(
            name="security.bughunter_classify",
            description=(
                "Classify one in-scope http(s) URL into BugHunter bug classes with a local "
                "pattern match. No network request is made."
            ),
            permission=PermissionTier.READ_ONLY,
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "maxLength": 2_000},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            timeout_s=120,
            tags=["security", "bughunter", "classification"],
        ),
        _bughunter_classify,
    )
    registry.register(
        ToolManifest(
            name="security.bughunter_skill",
            description="Read one BugHunter skill guide by name from the installed library.",
            permission=PermissionTier.READ_ONLY,
            input_schema={
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "minLength": 1, "maxLength": 80},
                },
                "required": ["skill"],
                "additionalProperties": False,
            },
            timeout_s=30,
            tags=["security", "bughunter", "skills"],
        ),
        _bughunter_skill,
    )
    registry.register(
        ToolManifest(
            name="security.bughunter_audit",
            description=(
                "Run the local read-only audit: static source scan of this project plus "
                "BugHunter classification of JARVIS's own local routes. Writes reports under "
                "the data directory; makes no network requests."
            ),
            permission=PermissionTier.READ_ONLY,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            timeout_s=300,
            tags=["security", "bughunter", "audit", "static-analysis"],
        ),
        _bughunter_audit,
    )
    registry.register(
        ToolManifest(
            name="security.bughunter_triage",
            description=(
                "Triage an existing .md finding from the BugHunter findings folder. The "
                "filename is confined to that folder."
            ),
            permission=PermissionTier.READ_ONLY,
            input_schema={
                "type": "object",
                "properties": {
                    "finding": {"type": "string", "minLength": 5, "maxLength": 200},
                },
                "required": ["finding"],
                "additionalProperties": False,
            },
            timeout_s=120,
            tags=["security", "bughunter", "triage"],
        ),
        _bughunter_triage,
    )
    registry.register(
        ToolManifest(
            name="security.bughunter_report",
            description=(
                "Draft a disclosure report for an existing finding on one platform. Never "
                "overwrites an existing draft; approval-gated because it writes a new file."
            ),
            permission=PermissionTier.CONFIRM,
            input_schema={
                "type": "object",
                "properties": {
                    "finding": {"type": "string", "minLength": 5, "maxLength": 200},
                    "platform": {
                        "type": "string",
                        "enum": sorted(PLATFORMS),
                    },
                },
                "required": ["finding", "platform"],
                "additionalProperties": False,
            },
            timeout_s=120,
            tags=["security", "bughunter", "report"],
        ),
        _bughunter_report,
    )


__all__ = [
    "BUGHUNTER_ROOT",
    "BugHunterUnavailable",
    "DEFAULT_BUGHUNTER_ROOT",
    "DRAFTS_ROOT",
    "FINDINGS_ROOT",
    "PLATFORMS",
    "PROJECT_ROOT",
    "REPORT_ROOT",
    "capabilities",
    "classify_url",
    "draft_report",
    "local_audit",
    "read_skill",
    "register_bughunter_tools",
    "surface_local",
    "triage_finding",
]
