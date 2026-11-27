"""Provider-independent telephony primitives.

A phone line is a remote-control surface, so nothing here is open by default:
a provider, verified credentials and at least one authorised caller number must
all exist before a call route answers. The protocol keeps the call flow free of
provider-specific types, so Twilio is an adapter rather than the architecture.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


class TelephonyError(RuntimeError):
    """A call was refused, or could not be placed, for a stated reason."""


@dataclass
class CallState:
    """One live call and the run it spawned."""

    sid: str
    caller: str
    started_at: float = field(default_factory=time.time)
    status: str = "greeting"
    polls: int = 0
    transcript: list[str] = field(default_factory=list)
    run_id: str | None = None
    reply: str = ""
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sid": self.sid,
            "caller": self.caller,
            "status": self.status,
            "run_id": self.run_id,
            "turns": len(self.transcript),
            "polls": self.polls,
            "started_at": self.started_at,
        }


class TelephonyProvider(Protocol):
    """The narrow surface the gateway needs from a telephony vendor."""

    name: str

    def missing_settings(self) -> list[str]:
        """Names of the settings that still have to be supplied."""

    def verify_signature(
        self, url: str, params: Mapping[str, str], signature: str
    ) -> bool:
        """True only when the request provably came from the provider."""

    async def account(self) -> dict[str, Any]:
        """Return the provider account record, or raise TelephonyError."""

    async def create_call(
        self, *, to: str, url: str, message: str = ""
    ) -> dict[str, Any]:
        """Place one outbound call and return the provider's own response."""


__all__ = ["CallState", "TelephonyError", "TelephonyProvider"]
