from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = PROJECT_ROOT / "data" / "browser-profile"
_lock = threading.RLock()
_playwright: Any = None
_context: BrowserContext | None = None
_page: Page | None = None


def _get_page() -> Page:
    global _playwright, _context, _page
    with _lock:
        if _context is None:
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            _playwright = sync_playwright().start()
            _context = _playwright.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=False, viewport={"width": 1440, "height": 900},
                args=["--disable-session-crashed-bubble"],
            )
            _page = _context.pages[0] if _context.pages else _context.new_page()
        context = _context
        if context is None:
            raise RuntimeError("Browser context failed to initialize.")
        if _page is None or _page.is_closed():
            _page = context.new_page()
        return _page


def open_url(url: str) -> dict[str, Any]:
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only complete http:// or https:// URLs are allowed.")
    if len(value) > 2048:
        raise ValueError("URL is too long.")
    with _lock:
        page = _get_page()
        response = page.goto(value, wait_until="domcontentloaded", timeout=30000)
        return {"opened": True, "url": page.url, "title": page.title(),
                "http_status": response.status if response else None}


def page_snapshot() -> dict[str, Any]:
    with _lock:
        page = _get_page()
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        title = page.title()
        text = page.locator("body").inner_text(timeout=10000)
        return {"url": page.url, "title": title, "text": text[:12000],
                "truncated": len(text) > 12000}


def click_text(text: str) -> dict[str, Any]:
    value = text.strip()
    if not value or len(value) > 200:
        raise ValueError("Target text must be between 1 and 200 characters.")
    with _lock:
        page = _get_page()
        locator = page.get_by_text(value, exact=True).first
        locator.click(timeout=5000)
        return {"clicked_text": value, "url": page.url, "title": page.title()}


def type_text(text: str) -> dict[str, Any]:
    if not text or len(text) > 2000:
        raise ValueError("Text must contain between 1 and 2000 characters.")
    with _lock:
        page = _get_page()
        page.locator(":focus").fill(text, timeout=5000)
        return {"typed": True, "characters": len(text), "url": page.url}


def browser_status() -> dict[str, Any]:
    with _lock:
        if _context is None or _page is None or _page.is_closed():
            return {"running": False}
        return {"running": True, "url": _page.url, "title": _page.title()}


_browser_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-browser")


async def run(function: Any, *args: Any) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_browser_executor, partial(function, *args))


def list_tabs() -> dict[str, Any]:
    with _lock:
        page = _get_page()
        context = _context
        if context is None:
            raise RuntimeError("Browser context failed to initialize.")
        tabs = [{"index": index, "url": item.url, "title": item.title(),
                 "active": item == page}
                for index, item in enumerate(context.pages)]
        return {"tabs": tabs, "count": len(tabs)}


def new_tab(url: str = "about:blank") -> dict[str, Any]:
    global _page
    if url != "about:blank":
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only complete http:// or https:// URLs are allowed.")
    with _lock:
        context = _get_page().context
        _page = context.new_page()
        if url != "about:blank":
            response = _page.goto(url, wait_until="domcontentloaded", timeout=30000)
        else:
            response = None
        return {"opened": True, "url": _page.url, "title": _page.title(),
                "http_status": response.status if response else None}


def switch_tab(index: int) -> dict[str, Any]:
    global _page
    with _lock:
        pages = _get_page().context.pages
        if index < 0 or index >= len(pages):
            raise ValueError(f"Tab index must be between 0 and {len(pages) - 1}.")
        _page = pages[index]
        _page.bring_to_front()
        return {"active_tab": index, "url": _page.url, "title": _page.title()}


def navigate_history(direction: str) -> dict[str, Any]:
    if direction not in {"back", "forward", "reload"}:
        raise ValueError("Direction must be back, forward, or reload.")
    with _lock:
        page = _get_page()
        if direction == "back":
            page.go_back(wait_until="domcontentloaded", timeout=15000)
        elif direction == "forward":
            page.go_forward(wait_until="domcontentloaded", timeout=15000)
        else:
            page.reload(wait_until="domcontentloaded", timeout=15000)
        return {"action": direction, "url": page.url, "title": page.title()}


def inspect_form_fields() -> dict[str, Any]:
    """Describe visible editable form controls without reading secret values."""
    with _lock:
        page = _get_page()
        fields = page.locator("input, textarea, select").evaluate_all(
            """els => els.filter(e => {
                const s = getComputedStyle(e), r = e.getBoundingClientRect();
                return s.visibility !== 'hidden' && s.display !== 'none' &&
                    r.width > 0 && r.height > 0 && !e.disabled && !e.readOnly;
            }).map((e, index) => {
                const type = (e.getAttribute('type') || e.tagName.toLowerCase()).toLowerCase();
                const labels = e.labels ? Array.from(e.labels).map(x => x.innerText.trim()).filter(Boolean) : [];
                const aria = e.getAttribute('aria-label') || '';
                const placeholder = e.getAttribute('placeholder') || '';
                const name = e.getAttribute('name') || '';
                const options = e.tagName === 'SELECT' ? Array.from(e.options).map(o => ({
                    label: o.label, value: o.value, disabled: o.disabled
                })).slice(0, 50) : [];
                return {index, tag: e.tagName.toLowerCase(), type,
                    label: labels[0] || aria || '', placeholder, name,
                    required: !!e.required, options};
            }).filter(x => !['hidden','password','file','submit','button','reset','image'].includes(x.type))"""
        )
        return {"url": page.url, "title": page.title(), "fields": fields[:100],
                "count": len(fields), "note": "Password, file and button controls are intentionally excluded."}


def fill_form_field(label: str, value: str) -> dict[str, Any]:
    """Fill one non-sensitive field by its exact accessible label or placeholder."""
    target = label.strip()
    if not target or len(target) > 200:
        raise ValueError("Field label must be between 1 and 200 characters.")
    if len(value) > 2000:
        raise ValueError("Field value cannot exceed 2000 characters.")
    with _lock:
        page = _get_page()
        locator = page.get_by_label(target, exact=True)
        if locator.count() == 0:
            locator = page.get_by_placeholder(target, exact=True)
        if locator.count() != 1:
            raise ValueError("Field label must identify exactly one visible form field.")
        field = locator.first
        details = field.evaluate("""e => ({
            tag: e.tagName.toLowerCase(),
            type: (e.getAttribute('type') || '').toLowerCase(),
            disabled: !!e.disabled, readOnly: !!e.readOnly,
            visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)
        })""")
        if (not details["visible"] or details["disabled"] or details["readOnly"]
                or details["type"] in {"password", "file", "hidden", "submit", "button", "reset"}):
            raise ValueError("This field is hidden, disabled, read-only, or sensitive and cannot be filled.")
        if details["tag"] == "select":
            field.select_option(label=value, timeout=5000)
        else:
            field.fill(value, timeout=5000)
        return {"filled": True, "label": target, "url": page.url,
                "note": "The form was not submitted."}


def press_key(key: str) -> dict[str, Any]:
    allowed = {"Enter", "Tab", "Escape", "Backspace", "Delete", "ArrowUp",
               "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End",
               "PageUp", "PageDown", "Control+A", "Control+C", "Control+V",
               "Control+X", "Control+Z", "Control+L", "Control+T",
               "Control+W", "Control+Tab", "Shift+Tab"}
    if key not in allowed:
        raise ValueError("That keyboard shortcut is not in JARVIS's safe key allowlist.")
    with _lock:
        page = _get_page()
        page.keyboard.press(key)
        return {"pressed": key, "url": page.url, "title": page.title()}
