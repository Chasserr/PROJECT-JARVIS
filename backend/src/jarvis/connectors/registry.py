"""Connector registry.

Two rules make this honest rather than decorative:

1. **Authorisation is explicit.** When an allowlist is configured, a connector
   that is not on it reports ``not_configured`` and refuses to search. Absence of
   consent is never treated as consent.
2. **One failing source cannot hide another.** A fan-out search records the
   failure per source and returns the hits that did succeed, each attributed to
   the connector that produced it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Sequence
from typing import Any

from .base import Connector, SourceError, SourceHit, SourceState, SourceStatus, SourceUnauthorised

log = logging.getLogger(__name__)


class ConnectorRegistry:
    def __init__(
        self,
        *,
        allowlist: Iterable[str] | None = None,
        timeout_s: float = 20.0,
        max_results: int = 8,
    ) -> None:
        self._items: dict[str, Connector] = {}
        # ``None`` means "no allowlist configured"; an empty iterable means
        # "nothing is authorised", which is a meaningful and different state.
        self._allowlist: set[str] | None = None if allowlist is None else set(allowlist)
        self._timeout_s = timeout_s
        self._max_results = max(1, max_results)

    # -- registration -----------------------------------------------------
    def register(self, connector: Connector) -> None:
        if not connector.id:
            raise ValueError("connector id must not be empty")
        if connector.id in self._items:
            raise ValueError(f"connector already registered: {connector.id}")
        self._items[connector.id] = connector

    def get(self, source_id: str) -> Connector:
        connector = self._items.get(source_id)
        if connector is None:
            known = ", ".join(sorted(self._items)) or "none"
            raise SourceError(f"unknown source '{source_id}'. Known: {known}")
        return connector

    def all(self) -> list[Connector]:
        return [self._items[key] for key in sorted(self._items)]

    def __len__(self) -> int:
        return len(self._items)

    # -- authorisation ----------------------------------------------------
    def authorised(self, connector: Connector) -> bool:
        if self._allowlist is None:
            return True
        return connector.id in self._allowlist

    def state_of(self, connector: Connector) -> SourceStatus:
        if not self.authorised(connector):
            return SourceStatus(
                SourceState.NOT_CONFIGURED,
                f"not authorised: add '{connector.id}' to JARVIS_CONNECTOR_ALLOWLIST",
            )
        return connector.status()

    def describe(self) -> list[dict[str, Any]]:
        return [connector.describe(self.state_of(connector)) for connector in self.all()]

    # -- queries ----------------------------------------------------------
    def _resolve(self, sources: Sequence[str] | None) -> list[Connector]:
        if sources:
            return [self.get(source_id) for source_id in sources]
        return [item for item in self.all() if self.state_of(item).available]

    async def search(
        self,
        query: str,
        *,
        sources: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        needle = query.strip()
        if not needle:
            raise SourceError("search query must not be empty")
        per_source = max(1, min(limit or self._max_results, 50))
        targets = self._resolve(sources)
        if not targets:
            return {
                "query": needle,
                "hits": [],
                "sources": [],
                "errors": [],
                "note": "no authorised source is configured",
            }

        results = await asyncio.gather(
            *(self._search_one(item, needle, per_source) for item in targets),
            return_exceptions=False,
        )
        hits: list[SourceHit] = []
        reports: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for connector, (found, error) in zip(targets, results, strict=True):
            reports.append(
                {
                    "id": connector.id,
                    "state": SourceState.ERROR.value if error else SourceState.CONNECTED.value,
                    "count": len(found),
                    "detail": error or "",
                }
            )
            if error:
                errors.append({"source": connector.id, "error": error})
            hits.extend(found)

        hits.sort(key=lambda hit: hit.title.lower())
        return {
            "query": needle,
            "hits": [hit.as_dict() for hit in hits[: per_source * max(1, len(targets))]],
            "sources": reports,
            "errors": errors,
        }

    async def _search_one(
        self, connector: Connector, query: str, limit: int
    ) -> tuple[list[SourceHit], str | None]:
        try:
            state = self.state_of(connector)
            if not state.available:
                raise SourceUnauthorised(state.detail or "source is not available")
            found = await asyncio.wait_for(
                connector.search(query, limit=limit), timeout=self._timeout_s
            )
        except TimeoutError:
            return [], f"timed out after {self._timeout_s:.0f}s"
        except SourceUnauthorised as exc:
            return [], str(exc)
        except SourceError as exc:
            return [], str(exc)
        except Exception as exc:  # noqa: BLE001 - reported, never hidden
            log.warning("connector %s failed: %s", connector.id, exc)
            return [], f"{type(exc).__name__}: {exc}"
        cleaned = [
            hit
            for hit in found[:limit]
            if isinstance(hit, SourceHit) and hit.source == connector.id
        ]
        return cleaned, None

    async def read(self, source_id: str, locator: str, *, max_chars: int = 8000) -> dict[str, Any]:
        connector = self.get(source_id)
        state = self.state_of(connector)
        if not state.available:
            raise SourceUnauthorised(state.detail or "source is not available")
        try:
            payload = await asyncio.wait_for(
                connector.read(locator, max_chars=max_chars), timeout=self._timeout_s
            )
        except TimeoutError as exc:
            raise SourceError(f"{source_id} timed out after {self._timeout_s:.0f}s") from exc
        payload.setdefault("source", source_id)
        payload.setdefault("untrusted", True)
        return payload


__all__ = ["ConnectorRegistry"]
