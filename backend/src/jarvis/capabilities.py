"""Runtime capability probes.

An agent is only reported as ``connected`` when the capabilities its job needs
have passed a real check here. Anything this module cannot verify is reported as
unavailable rather than assumed, so the dashboard never shows a green pill for a
feature that has no implementation behind it.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .tools.execution import project_root, run_command, write_roots
from .tools.vision import probe_vision

# Capabilities that still have no implementation in the core at all. They are
# listed explicitly so "not implemented" can never be confused with "unknown".
UNIMPLEMENTED: dict[str, str] = {
    "scanner": "no dependency or vulnerability scanner is wired in",
    "desktop_control": "mouse/keyboard control lives only in the legacy PC CONTROL runtime",
    "creative_gen": "no image or video generation backend is connected",
}

_CACHE_TTL_S = 300.0
_cache: dict[str, Any] = {"at": 0.0, "value": None}


async def probe_llm(settings: Settings) -> dict[str, Any]:
    """Is a local model runtime actually answering?"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(settings.ollama_url.rstrip("/") + "/api/tags")
            response.raise_for_status()
            models = [item.get("name", "") for item in response.json().get("models", [])]
    except (httpx.HTTPError, ValueError) as exc:
        return {"available": False, "error": f"model runtime unreachable: {exc}"}
    if not models:
        return {"available": False, "error": "no models are installed"}
    return {"available": True, "models": models[:20], "count": len(models)}


async def probe_brave(settings: Settings) -> dict[str, Any]:
    """A stored key is not enough; the search API has to answer."""
    key = settings.brave_api_key
    if key is None:
        return {"available": False, "error": "JARVIS_BRAVE_API_KEY is not set"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": "jarvis", "count": 1},
                headers={
                    "X-Subscription-Token": key.get_secret_value(),
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            hits = response.json().get("web", {}).get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        return {"available": False, "error": f"web search failed: {exc}"}
    if not hits:
        return {"available": False, "error": "web search returned no results"}
    return {"available": True, "sample": str(hits[0].get("title", ""))[:120]}


async def probe_shell(settings: Settings) -> dict[str, Any]:
    """Actually execute an allowlisted command through the sandbox."""
    if not settings.shell_enabled:
        return {"available": False, "error": "shell execution is disabled by configuration"}
    try:
        result = await run_command(
            [sys.executable, "-c", "print('jarvis-shell-probe')"],
            settings=settings,
            cwd=project_root(settings),
            timeout_s=20.0,
            max_chars=2000,
        )
    except Exception as exc:  # noqa: BLE001 - reported as state
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    ok = result["exit_code"] == 0 and "jarvis-shell-probe" in result["stdout"]
    if not ok:
        return {"available": False, "error": "probe command did not return the expected output"}
    return {"available": True, "detail": "allowlisted command executed in the project root"}


def probe_code_edit(settings: Settings) -> dict[str, Any]:
    """Prove a writable root exists by writing and removing a probe file."""
    roots = write_roots(settings)
    if not roots:
        return {"available": False, "error": "no writable root is configured"}
    target_dir = Path(settings.data_dir)
    root = next((item for item in roots if target_dir.resolve().is_relative_to(item)), roots[0])
    probe = root / ".jarvis-write-probe.tmp"
    try:
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return {"available": False, "error": f"write probe failed: {exc}"}
    return {"available": True, "detail": f"writable root {root}"}


async def probe_browser(settings: Settings) -> dict[str, Any]:
    """Launch headless Chromium and load a blank page."""

    def launch() -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto("about:blank")
            finally:
                browser.close()

    try:
        await asyncio.wait_for(asyncio.to_thread(launch), timeout=45.0)
    except Exception as exc:  # noqa: BLE001 - reported as state
        return {"available": False, "error": f"browser launch failed: {type(exc).__name__}: {exc}"}
    domains = settings.browser_allowed_domains
    return {
        "available": True,
        "detail": (
            f"headless Chromium launched; {len(domains)} domain(s) authorised"
            if domains
            else "headless Chromium launched; no domains authorised yet"
        ),
    }


async def probe_runtime(settings: Settings, *, use_cache: bool = True) -> dict[str, Any]:
    """Probe every capability the roster can declare, once per minute."""
    now = time.monotonic()
    if use_cache and _cache["value"] is not None and now - _cache["at"] < _CACHE_TTL_S:
        return _cache["value"]

    # Probe concurrently: the vision check loads a model, so running these in
    # sequence made the first /agents call take as long as all three combined.
    llm, brave, vision, shell, browser = await asyncio.gather(
        probe_llm(settings),
        probe_brave(settings),
        probe_vision(
            settings.ollama_url,
            model=settings.vision_model,
            timeout=settings.vision_timeout_s,
        ),
        probe_shell(settings),
        probe_browser(settings),
    )
    probes: dict[str, Any] = {
        "llm": llm,
        "brave": brave,
        "vision": vision,
        "shell": shell,
        "browser_automation": browser,
        "code_edit": probe_code_edit(settings),
    }
    for key, reason in UNIMPLEMENTED.items():
        probes[key] = {"available": False, "error": reason}

    if use_cache:
        _cache.update({"at": now, "value": probes})
    return probes


def reset_cache() -> None:
    _cache.update({"at": 0.0, "value": None})


__all__ = [
    "UNIMPLEMENTED",
    "probe_brave",
    "probe_browser",
    "probe_code_edit",
    "probe_llm",
    "probe_runtime",
    "probe_shell",
    "reset_cache",
]
