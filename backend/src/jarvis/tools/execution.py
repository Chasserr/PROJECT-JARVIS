"""Bounded execution tools: shell, file writing, real browser.

These are the tools the Engineer, Testing and Browser agents were missing. All
three are deliberately narrow:

- ``shell.run`` takes an argv list (never a shell string), only runs an
  allowlisted executable, only inside the project root, with a scrubbed
  environment and a hard timeout.
- ``files.write`` only writes inside explicitly authorised roots and refuses
  anything under ``.git``.
- ``browser.open`` only visits hosts on an explicit allowlist, headless, with no
  stored profile and no downloads.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..config import Settings
from ..security.permissions import PermissionTier
from .manifest import ToolManifest
from .registry import ToolContext, ToolRegistry, ToolResult

# Variables kept when spawning a child process. Everything else (including any
# JARVIS_* secret) is dropped, so a child cannot read the agent's credentials.
_SAFE_ENV_KEYS = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "LC_ALL", "APPDATA",
    "LOCALAPPDATA", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
}
_MAX_WRITE_BYTES = 1_000_000


def project_root(settings: Settings) -> Path:
    root = settings.project_root or Path.cwd()
    try:
        return Path(root).expanduser().resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"project root is not available: {root}") from exc


def write_roots(settings: Settings) -> list[Path]:
    roots: list[Path] = []
    candidates = list(settings.file_write_roots) or [settings.project_root or Path.cwd()]
    for candidate in candidates:
        try:
            resolved = Path(candidate).expanduser().resolve(strict=True)
        except OSError:
            continue
        if resolved.is_dir():
            roots.append(resolved)
    return roots


def _normalise_command(name: str) -> str:
    stem = Path(name).name.lower()
    return stem[:-4] if stem.endswith(".exe") else stem


def _safe_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key.upper() in _SAFE_ENV_KEYS}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


async def run_command(
    argv: list[str],
    *,
    settings: Settings,
    cwd: Path,
    timeout_s: float,
    max_chars: int,
) -> dict[str, Any]:
    """Run one allowlisted command. Shared by the tool and the capability probe."""
    if not argv:
        raise ValueError("argv must not be empty")
    if not settings.shell_enabled:
        raise PermissionError("shell execution is disabled (JARVIS_SHELL_ENABLED=false)")
    allowed = {_normalise_command(item) for item in settings.shell_allowed_commands}
    command = _normalise_command(argv[0])
    if command not in allowed:
        raise PermissionError(
            f"command '{command}' is not allowlisted; allowed: {', '.join(sorted(allowed))}"
        )
    executable = shutil.which(argv[0])
    if executable is None:
        raise FileNotFoundError(f"command not found on PATH: {argv[0]}")
    root = project_root(settings)
    resolved_cwd = Path(cwd).expanduser().resolve(strict=True)
    if not resolved_cwd.is_relative_to(root):
        raise PermissionError("working directory is outside the project root")

    process = await asyncio.create_subprocess_exec(
        executable,
        *argv[1:],
        cwd=str(resolved_cwd),
        env=_safe_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise TimeoutError(f"command timed out after {timeout_s:.0f}s") from None
    return {
        "command": [command, *argv[1:]],
        "exit_code": process.returncode,
        "stdout": stdout.decode("utf-8", "replace")[:max_chars],
        "stderr": stderr.decode("utf-8", "replace")[:max_chars],
        "truncated": len(stdout) > max_chars or len(stderr) > max_chars,
        "cwd": str(resolved_cwd),
    }


def _shell(args: dict[str, Any], context: ToolContext) -> Any:
    settings = context.settings
    argv = [str(item) for item in args["argv"]]
    cwd = Path(args.get("cwd") or project_root(settings))
    timeout_s = float(args.get("timeout_s", settings.shell_timeout_s))

    async def run() -> ToolResult:
        try:
            payload = await run_command(
                argv,
                settings=settings,
                cwd=cwd,
                timeout_s=timeout_s,
                max_chars=settings.shell_max_output_chars,
            )
        except (PermissionError, FileNotFoundError, ValueError, TimeoutError, OSError) as exc:
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        ok = payload["exit_code"] == 0
        return ToolResult(
            ok=ok,
            output=payload,
            error=None if ok else f"exit code {payload['exit_code']}",
        )

    return run()


def _write_file(args: dict[str, Any], context: ToolContext) -> ToolResult:
    settings = context.settings
    roots = write_roots(settings)
    if not roots:
        return ToolResult(ok=False, error="no writable root is configured")
    target = Path(args["path"]).expanduser()
    if not target.is_absolute():
        target = roots[0] / target
    parent = target.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        resolved = target.resolve(strict=False)
    except OSError as exc:
        return ToolResult(ok=False, error=f"cannot prepare path: {exc}")
    root = next((item for item in roots if resolved.is_relative_to(item)), None)
    if root is None:
        return ToolResult(ok=False, error="path is outside every writable root")
    if ".git" in resolved.parts:
        return ToolResult(ok=False, error="refusing to write inside .git")
    content = str(args["content"])
    payload = content.encode("utf-8")
    if len(payload) > _MAX_WRITE_BYTES:
        return ToolResult(ok=False, error=f"content exceeds {_MAX_WRITE_BYTES} bytes")
    mode = "a" if args.get("mode") == "append" else "w"
    existed = resolved.exists()
    try:
        with resolved.open(mode, encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except OSError as exc:
        return ToolResult(ok=False, error=f"write failed: {exc}")
    return ToolResult(
        ok=True,
        output={
            "path": str(resolved),
            "relative": str(resolved.relative_to(root)).replace("\\", "/"),
            "bytes": len(payload),
            "mode": "append" if mode == "a" else "write",
            "created": not existed,
        },
    )


def _blocked_host(host: str) -> bool:
    lowered = host.lower()
    if lowered in {"localhost", "metadata", "instance-data"} or lowered.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return not address.is_global


def _domain_allowed(host: str, allowed: list[str]) -> bool:
    host = host.lower().strip(".")
    for entry in allowed:
        candidate = entry.lower().strip().strip(".")
        if not candidate:
            continue
        if candidate.startswith("*."):
            suffix = candidate[2:]
            if host == suffix or host.endswith("." + suffix):
                return True
        elif host == candidate or host.endswith("." + candidate):
            return True
    return False


def _browser_sync(url: str, *, timeout_ms: int, max_chars: int) -> dict[str, Any]:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            page = browser.new_page(accept_downloads=False)
            page.set_default_timeout(timeout_ms)
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            title = page.title()
            text = page.inner_text("body")[:max_chars]
            links = page.eval_on_selector_all(
                "a[href]", "els => els.slice(0, 60).map(e => e.href)"
            )
            return {
                "url": page.url,
                "title": title,
                "text": text,
                "links": links,
                "status": response.status if response is not None else None,
            }
        except PlaywrightError as exc:
            raise RuntimeError(f"browser error: {exc}") from exc
        finally:
            browser.close()


def _browser(args: dict[str, Any], context: ToolContext) -> Any:
    settings = context.settings
    url = str(args["url"]).strip()

    async def open_page() -> ToolResult:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            return ToolResult(ok=False, error="only http and https URLs are allowed")
        host = parsed.hostname or ""
        if not host or _blocked_host(host):
            return ToolResult(ok=False, error=f"refusing to open non-public host: {host}")
        if not _domain_allowed(host, settings.browser_allowed_domains):
            return ToolResult(
                ok=False,
                error=(
                    f"host '{host}' is not authorised; add it to "
                    "JARVIS_BROWSER_ALLOWED_DOMAINS"
                ),
            )
        try:
            payload = await asyncio.to_thread(
                _browser_sync,
                url,
                timeout_ms=settings.browser_timeout_ms,
                max_chars=settings.browser_max_chars,
            )
        except Exception as exc:  # noqa: BLE001 - reported to the model
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        payload["untrusted"] = True
        return ToolResult(ok=True, output=payload)

    return open_page()


def register_execution_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolManifest(
            name="shell.run",
            description=(
                "Run one allowlisted command inside the project directory and return its "
                "exit code, stdout and stderr. Pass an argv list, not a shell string. "
                "Every call pauses for explicit approval."
            ),
            permission=PermissionTier.CONFIRM,
            dangerous=True,
            input_schema={
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "items": {"type": "string", "maxLength": 2000},
                        "description": "Command and arguments, e.g. ['pytest', '-q'].",
                    },
                    "cwd": {
                        "type": "string",
                        "maxLength": 1000,
                        "description": "Optional working directory inside the project root.",
                    },
                    "timeout_s": {"type": "number", "minimum": 1, "maximum": 300},
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
            timeout_s=120,
            tags=["shell", "development", "testing"],
        ),
        _shell,
    )
    registry.register(
        ToolManifest(
            name="files.write",
            description=(
                "Create or overwrite a UTF-8 text file inside an authorised project root. "
                "Use this to apply a reviewed code change. Pauses for approval."
            ),
            permission=PermissionTier.CONFIRM,
            dangerous=True,
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "content": {"type": "string", "maxLength": 1_000_000},
                    "mode": {"type": "string", "enum": ["write", "append"]},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            tags=["files", "development", "code"],
        ),
        _write_file,
    )
    registry.register(
        ToolManifest(
            name="browser.open",
            description=(
                "Open an authorised https page in a real headless Chromium browser and "
                "return its title, visible text and links. Hosts must be on the domain "
                "allowlist."
            ),
            permission=PermissionTier.READ_ONLY,
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "minLength": 8, "maxLength": 2048},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            timeout_s=90,
            tags=["browser", "web", "automation"],
        ),
        _browser,
    )


__all__ = [
    "project_root",
    "register_execution_tools",
    "run_command",
    "write_roots",
]
