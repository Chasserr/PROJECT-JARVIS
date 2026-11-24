from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventBus:
    """Small local async pub/sub bus. Redis can implement this interface later."""

    def __init__(self, queue_size: int = 256) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be positive")
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size)
        self._closed = False

    async def publish(self, event: Event) -> None:
        if self._closed:
            raise RuntimeError("event bus is closed")
        await self._queue.put(event)

    async def next_event(self) -> Event:
        if self._closed and self._queue.empty():
            raise RuntimeError("event bus is closed")
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

    def close(self) -> None:
        self._closed = True
