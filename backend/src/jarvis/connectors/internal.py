"""Internal connector: JARVIS's own memory and notes.

This is the one source that needs no credentials because JARVIS owns the data.
It is still a connector so a multi-source query can include it with attribution.
"""

from __future__ import annotations

from typing import Any

from ..memory.store import MemoryStore
from ..notes.store import NoteStore
from .base import Connector, SourceHit, SourceState, SourceStatus


class MemoryConnector(Connector):
    id = "memory"
    label = "Memory & notes"
    kind = "internal"
    scopes = ("read", "search")
    requires = ()

    def __init__(self, memory: MemoryStore, notes: NoteStore) -> None:
        self._memory = memory
        self._notes = notes

    def status(self) -> SourceStatus:
        try:
            count = self._memory.count()
        except Exception as exc:  # noqa: BLE001 - reported as state
            return SourceStatus(SourceState.ERROR, f"memory store unavailable: {exc}")
        return SourceStatus(SourceState.CONNECTED, f"{count} stored memories")

    async def search(self, query: str, *, limit: int) -> list[SourceHit]:
        hits: list[SourceHit] = []
        for item in await self._memory.search(query, limit):
            hits.append(
                SourceHit(
                    source=self.id,
                    title=f"memory [{item.kind}]",
                    locator=f"memory:{item.id}",
                    snippet=item.content[:300],
                    metadata={"kind": str(item.kind), "tags": item.tags, "created": item.created_at},
                )
            )
        needle = query.lower()
        for note in self._notes.list(50):
            body = note.body or ""
            if needle not in note.title.lower() and needle not in body.lower():
                continue
            hits.append(
                SourceHit(
                    source=self.id,
                    title=note.title,
                    locator=f"note:{note.id}",
                    snippet=" ".join(body.split())[:300],
                    metadata={"kind": "note"},
                )
            )
            if len(hits) >= limit:
                break
        return hits[:limit]

    async def read(self, locator: str, *, max_chars: int) -> dict[str, Any]:
        kind, _, ident = locator.partition(":")
        if kind == "note":
            note = self._notes.get(ident)
            if note is None:
                raise KeyError(f"no note {ident}")
            body = note.body or ""
            return {
                "title": note.title,
                "locator": locator,
                "text": body[:max_chars],
                "truncated": len(body) > max_chars,
            }
        if kind == "memory":
            for item in self._memory.list(200):
                if item.id == ident:
                    return {
                        "title": f"memory [{item.kind}]",
                        "locator": locator,
                        "text": item.content[:max_chars],
                        "truncated": len(item.content) > max_chars,
                    }
            raise KeyError(f"no memory {ident}")
        raise KeyError("locator must look like memory:<id> or note:<id>")


__all__ = ["MemoryConnector"]
