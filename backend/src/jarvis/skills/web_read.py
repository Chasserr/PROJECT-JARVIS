"""Readable-text extraction for public web pages."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from ..net.safe_fetch import Resolver, fetch_text


async def read_url(
    url: str,
    *,
    settings: Settings,
    max_chars: int | None = None,
    client: httpx.AsyncClient | None = None,
    resolver: Resolver | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "max_bytes": settings.web_read_max_bytes,
        "max_chars": max_chars or settings.web_read_max_chars,
        "timeout": settings.web_read_timeout_s,
        "client": client,
    }
    if resolver is not None:
        kwargs["resolver"] = resolver
    result = await fetch_text(url, **kwargs)
    return {
        "url": result.url,
        "status": result.status,
        "content_type": result.content_type,
        "text": result.text,
        "truncated": result.truncated,
        "untrusted": True,
    }


__all__ = ["read_url"]
