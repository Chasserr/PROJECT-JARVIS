"""Brave Search adapter. Returns only the fields the agent needs."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings

_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


async def brave_search(
    query: str,
    *,
    count: int,
    settings: Settings,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    key = settings.brave_api_key.get_secret_value() if settings.brave_api_key else ""
    if not key:
        raise ValueError(
            "BRAVE_API_KEY is not configured; set JARVIS_BRAVE_API_KEY to enable web.search"
        )
    limit = max(1, min(count, 10))
    own_client = client is None
    active = client or httpx.AsyncClient(timeout=settings.web_read_timeout_s)
    try:
        response = await active.get(
            _SEARCH_URL,
            params={"q": query, "count": limit},
            headers={"Accept": "application/json", "X-Subscription-Token": key},
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if own_client:
            await active.aclose()

    raw_results = (payload.get("web") or {}).get("results") or []
    results: list[dict[str, Any]] = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": str(item.get("title", ""))[:300],
                "url": str(item.get("url", ""))[:2048],
                "description": str(item.get("description", ""))[:1000],
            }
        )
    return results


__all__ = ["brave_search"]
