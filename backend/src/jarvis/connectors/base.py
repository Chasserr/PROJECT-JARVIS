"""Connector contract.

A connector is one *explicitly authorised* data source. It reports its own
state, so "not configured" can never be displayed as "connected", and it never
raises out of :meth:`search` — failures are returned as data so one broken
source cannot take down a multi-source query.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SourceState(StrEnum):
    CONNECTED = "connected"
    NOT_CONFIGURED = "not_configured"
    ERROR = "error"


class SourceError(RuntimeError):
    """A connector could not complete the request."""


class SourceUnauthorised(SourceError):
    """The connector exists but the user has not authorised it."""


@dataclass(frozen=True)
class SourceHit:
    """One attributed result. ``source`` is always the connector id."""

    source: str
    title: str
    locator: str
    snippet: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "locator": self.locator,
            "snippet": self.snippet,
            "metadata": self.metadata,
            "untrusted": True,
        }


@dataclass(frozen=True)
class SourceStatus:
    state: SourceState
    detail: str = ""

    @property
    def available(self) -> bool:
        return self.state is SourceState.CONNECTED


class Connector(ABC):
    """Read-only data source with an explicit scope list."""

    id: str = ""
    label: str = ""
    kind: str = "local"
    # What the connector is allowed to do. Kept explicit so the dashboard can
    # show it, and so a future write connector cannot silently inherit "read".
    scopes: tuple[str, ...] = ("read",)
    # Environment variable names needed before the connector can work. Used for
    # honest "not configured" messages, never to hold values.
    requires: tuple[str, ...] = ()

    @abstractmethod
    def status(self) -> SourceStatus:
        """Report the current state by inspecting real configuration."""

    @abstractmethod
    async def search(self, query: str, *, limit: int) -> list[SourceHit]:
        """Return attributed hits. Must not raise; return ``[]`` on no match."""

    async def read(self, locator: str, *, max_chars: int) -> dict[str, Any]:
        raise SourceError(f"{self.id} does not support reading a single item")

    def describe(self, status: SourceStatus | None = None) -> dict[str, Any]:
        state = status or self.status()
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "scopes": list(self.scopes),
            "requires": list(self.requires),
            "state": state.state.value,
            "detail": state.detail,
        }


__all__ = [
    "Connector",
    "SourceError",
    "SourceHit",
    "SourceState",
    "SourceStatus",
    "SourceUnauthorised",
]
