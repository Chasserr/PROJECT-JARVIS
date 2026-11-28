"""Read-only static source scan: credential patterns and risky calls.

Ported from the remote ``jarvis.skills.security_scanner`` onto the local tool
architecture. The scan is bounded (file count, file size, total bytes), never
follows symlinks, skips VCS/dependency/build directories, and writes exactly one
report inside the tree it scanned. Secret values are never copied into the
report: a match records the rule, file and line and says the value is redacted.

This is source inspection, not a penetration test: no network request, no code
execution and no source modification.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..security.permissions import PermissionTier
from .execution import project_root
from .manifest import ToolManifest
from .registry import ToolContext, ToolRegistry, ToolResult

MAX_FILES = 3_000
MAX_FILE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 100_000_000
REPORT_DIR_NAME = "security-reports"
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".next", "dist", "build", "coverage", ".idea", ".vscode",
    "data", "target",
}
TEXT_SUFFIXES = {
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".env", ".ps1", ".bat", ".cmd", ".sh", ".sql", ".html", ".htm",
    ".css", ".scss", ".md", ".txt", ".xml", ".properties",
}
SECRET_PATTERNS = [
    ("SEC001", "high", "Private key material", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("SEC002", "critical", "AWS access key identifier", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("SEC003", "high", "GitHub personal access token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("SEC004", "high", "OpenAI-style API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("SEC005", "high", "Possible hard-coded credential assignment",
     re.compile(r"""(?i)\b(?:api[_-]?key|client[_-]?secret|secret[_-]?key|password|passwd|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*["']([^"' \t\r\n]{8,})["']""")),
]
PLACEHOLDER = re.compile(
    r"(?i)(example|placeholder|synthetic|invented|change.?me|your[_-]|dummy|redacted|"
    r"replace[_-]?this|not.?real|test.?only|(?:^|[_-])(?:test|fake|mock|fixture)(?:[_-]|$)|"
    r"xxxx|<[^>]+>|^none$)"
)
PYTHON_CALL_RULES = {
    "eval": ("CODE001", "high", "Dynamic eval() execution"),
    "exec": ("CODE002", "high", "Dynamic exec() execution"),
    "system": ("CODE003", "medium", "Direct operating-system command execution"),
    "popen": ("CODE004", "medium", "Direct process creation"),
    "loads": ("CODE005", "medium", "Deserialization via pickle.loads()"),
    "mktemp": ("CODE006", "medium", "Race-prone tempfile.mktemp()"),
}
SKIP_NAMES = {"security_scanner.py"}


def _python_findings(path: Path, source: str, relative: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError:
        return []
    findings: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else ""
        )
        chain = ""
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            chain = f"{func.value.id}.{func.attr}"
        rule = None
        if name in {"eval", "exec"}:
            rule = PYTHON_CALL_RULES[name]
        elif chain in {"os.system", "os.popen"}:
            rule = PYTHON_CALL_RULES["system" if name == "system" else "popen"]
        elif chain == "pickle.loads":
            rule = PYTHON_CALL_RULES["loads"]
        elif chain == "tempfile.mktemp":
            rule = PYTHON_CALL_RULES["mktemp"]
        elif chain in {"subprocess.run", "subprocess.call", "subprocess.Popen"}:
            if any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant)
                   and keyword.value.value is True for keyword in node.keywords):
                rule = ("CODE007", "high", "Subprocess invoked with shell=True")
        elif chain in {"requests.get", "requests.post", "requests.put", "httpx.get", "httpx.post"}:
            if any(keyword.arg == "verify" and isinstance(keyword.value, ast.Constant)
                   and keyword.value.value is False for keyword in node.keywords):
                rule = ("CODE008", "high", "TLS certificate verification disabled")
        elif chain == "yaml.load":
            has_safe_loader = any(
                keyword.arg == "Loader"
                and isinstance(keyword.value, ast.Attribute)
                and keyword.value.attr in {"SafeLoader", "CSafeLoader"}
                for keyword in node.keywords
            )
            if not has_safe_loader:
                rule = ("CODE009", "medium", "yaml.load() without an explicit safe loader")
        if rule:
            rule_id, severity, title = rule
            findings.append({
                "rule_id": rule_id, "severity": severity, "title": title,
                "file": relative, "line": getattr(node, "lineno", 1),
                "evidence": "Potentially risky API usage; review surrounding code.",
            })
    return findings


def _inside(root: Path, candidate: Path) -> bool:
    return candidate == root or root in candidate.parents


def report_dir_for(root: str | Path, preferred: str | Path | None = None) -> Path:
    """Return the report directory for a scan of ``root``.

    A report is only ever written inside the tree that was scanned, so a
    preferred directory (the configured data directory) is used when it lives
    inside ``root`` and replaced by ``<root>/data`` when it does not.
    """
    resolved_root = Path(root).resolve()
    if preferred is not None:
        candidate = Path(preferred).resolve()
        if _inside(resolved_root, candidate):
            return candidate
    return resolved_root / "data" / REPORT_DIR_NAME


def scan_project(project_root: str | Path, report_dir: str | Path) -> dict[str, Any]:
    """Read-only source scan limited to the supplied project root; writes only its report."""
    root = Path(project_root).resolve(strict=True)
    report_path = Path(report_dir).resolve()
    if not root.is_dir():
        raise ValueError("Project scan root must be a directory.")
    if report_path != root and root not in report_path.parents:
        raise ValueError("Security report directory must be inside the project root.")

    findings: list[dict[str, Any]] = []
    scanned_files = 0
    skipped_files = 0
    scanned_bytes = 0
    truncated = False

    for current_dir, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
        dir_names[:] = [
            name for name in dir_names
            if name.lower() not in EXCLUDED_DIRS
            and not (Path(current_dir) / name).is_symlink()
        ]
        for file_name in file_names:
            candidate = Path(current_dir) / file_name
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    skipped_files += 1
                    continue
                relative_path = candidate.relative_to(root)
                if candidate.name in SKIP_NAMES:
                    continue
                if candidate.suffix.lower() not in TEXT_SUFFIXES and not candidate.name.lower().startswith(".env"):
                    continue
                size = candidate.stat().st_size
                if size > MAX_FILE_BYTES or scanned_bytes + size > MAX_TOTAL_BYTES:
                    skipped_files += 1
                    continue
                if scanned_files >= MAX_FILES:
                    truncated = True
                    break
                raw = candidate.read_bytes()
                if b"\x00" in raw:
                    skipped_files += 1
                    continue
                source = raw.decode("utf-8", errors="replace")
                scanned_files += 1
                scanned_bytes += len(raw)
                relative = relative_path.as_posix()

                for rule_id, severity, title, pattern in SECRET_PATTERNS:
                    for match in pattern.finditer(source):
                        if rule_id == "SEC005":
                            value = match.group(1)
                            if PLACEHOLDER.search(value):
                                continue
                        line = source.count("\n", 0, match.start()) + 1
                        findings.append({
                            "rule_id": rule_id, "severity": severity, "title": title,
                            "file": relative, "line": line,
                            "evidence": "Matched credential-like content; secret value is redacted.",
                        })
                if candidate.suffix.lower() == ".py":
                    findings.extend(_python_findings(candidate, source, relative))
            except OSError:
                skipped_files += 1
        if truncated:
            break

    findings.sort(key=lambda item: (
        {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(item["severity"], 4),
        item["file"], item["line"], item["rule_id"],
    ))
    counts = {level: sum(1 for item in findings if item["severity"] == level)
              for level in ("critical", "high", "medium", "low")}
    report: dict[str, Any] = {
        "scan_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
        "created_at": datetime.now(UTC).isoformat(),
        "scope": str(root),
        "mode": "read_only_local_static_scan",
        "scanned_files": scanned_files,
        "skipped_files": skipped_files,
        "scanned_bytes": scanned_bytes,
        "truncated": truncated,
        "summary": {
            "total_findings": len(findings),
            "critical": counts["critical"], "high": counts["high"],
            "medium": counts["medium"], "low": counts["low"],
        },
        "findings": findings,
        "limitations": [
            "Static checks only; this is not a penetration test or a complete vulnerability assessment.",
            "No network requests, exploit attempts, code execution, or source-file modifications are performed.",
            "Secrets are never included in report evidence; review flagged files locally.",
            "Generated data, dependency caches, virtual environments, and VCS metadata are excluded.",
        ],
    }
    report_dir_path = Path(report_dir)
    report_dir_path.mkdir(parents=True, exist_ok=True)
    latest = report_dir_path / "latest.json"
    temp = report_dir_path / "latest.json.tmp"
    temp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temp.replace(latest)
    return report


def load_latest_report(report_dir: str | Path) -> dict[str, Any] | None:
    path = Path(report_dir) / "latest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


async def _source_scan(args: dict[str, Any], context: ToolContext) -> ToolResult:
    allowed = project_root(context.settings)
    try:
        root = Path(args.get("root") or allowed).expanduser().resolve(strict=True)
    except OSError:
        return ToolResult(ok=False, error=f"scan root is not available: {args.get('root')}")
    if root != allowed and allowed not in root.parents:
        return ToolResult(
            ok=False, error=f"scan root must stay inside the project root: {allowed}"
        )
    preferred = Path(context.settings.data_dir) / REPORT_DIR_NAME
    report_dir = report_dir_for(root, preferred)
    try:
        report = await asyncio.to_thread(scan_project, root, report_dir)
    except (OSError, ValueError) as exc:
        return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    return ToolResult(
        ok=True,
        output={
            "report": str(report_dir / "latest.json"),
            "scope": report["scope"],
            "scanned_files": report["scanned_files"],
            "skipped_files": report["skipped_files"],
            "truncated": report["truncated"],
            "summary": report["summary"],
            "findings": report["findings"][:25],
            "findings_truncated": len(report["findings"]) > 25,
            "limitations": report["limitations"],
        },
    )


def register_source_scan_tool(registry: ToolRegistry) -> None:
    registry.register(
        ToolManifest(
            name="security.source_scan",
            description=(
                "Statically scan project source for credential patterns and risky calls "
                "(eval/exec, shell=True, pickle.loads, disabled TLS verification, unsafe "
                "yaml.load). Read-only and bounded: writes one report under the data "
                "directory and never copies a matched secret into it."
            ),
            permission=PermissionTier.READ_ONLY,
            input_schema={
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Directory to scan; must be inside the project root.",
                    },
                },
                "additionalProperties": False,
            },
            timeout_s=240,
            tags=["security", "static-analysis", "secrets", "audit"],
        ),
        _source_scan,
    )


__all__ = [
    "load_latest_report",
    "register_source_scan_tool",
    "report_dir_for",
    "scan_project",
]
