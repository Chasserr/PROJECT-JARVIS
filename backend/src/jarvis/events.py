"""In-process event bus with a durable SQLite outbox.

The bus is deliberately small: publish persists an event and then awaits
subscribers. A Redis Streams adapter can implement the same interface later
without changing callers.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .db import Database

log = logging.getLogger(__name__)

EventHandler = Callable[["Event"], Awaitable[None]]


class EventType:
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    TOOL_CALLED = "tool.called"
    APPROVAL_REQUESTED = "approval.requested"
    MEMORY_CREATED = "memory.created"
    MEMORY_DELETED = "memory.deleted"
    AUDIT_APPENDED = "audit.appended"


@dataclass(frozen=True)
class Event:
    id: str
    type: str
    payload: dict[str, Any]
    created_at: float


class EventBus:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._wildcard: list[EventHandler] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        self._wildcard.append(handler)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> Event:
        event = Event(
            id=str(uuid.uuid4()),
            type=event_type,
            payload=payload,
            created_at=time.time(),
        )
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO outbox (id, type, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    event.id,
                    event.type,
                    json.dumps(event.payload, ensure_ascii=False, default=str),
                    event.created_at,
                ),
            )
        handlers = [*self._subscribers.get(event_type, []), *self._wildcard]
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                log.exception("event handler failed for %s", event_type)
        return event

    def pending(self, limit: int = 100) -> list[Event]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM outbox WHERE consumed = 0 ORDER BY created_at ASC LIMIT ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()
        return [
            Event(
                id=row["id"],
                type=row["type"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def mark_consumed(self, event_id: str) -> None:
        with self._db.connection() as conn:
            conn.execute("UPDATE outbox SET consumed = 1 WHERE id = ?", (event_id,))
