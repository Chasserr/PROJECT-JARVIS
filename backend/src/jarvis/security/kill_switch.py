"""Persistent global kill switch. Engaged means no new agent work starts."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from ..db import Database

_KEY = "kill_switch"


class KillSwitchEngaged(RuntimeError):
    """Raised when work is attempted while the global kill switch is engaged."""


@dataclass(frozen=True)
class KillSwitchStatus:
    engaged: bool
    reason: str | None = None
    updated_at: float | None = None


class KillSwitch:
    def __init__(self, db: Database) -> None:
        self._db = db

    def status(self) -> KillSwitchStatus:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT value, updated_at FROM system_flags WHERE key = ?", (_KEY,)
            ).fetchone()
        if row is None:
            return KillSwitchStatus(engaged=False)
        value = json.loads(row["value"])
        return KillSwitchStatus(
            engaged=bool(value.get("engaged")),
            reason=value.get("reason"),
            updated_at=row["updated_at"],
        )

    def is_engaged(self) -> bool:
        return self.status().engaged

    def engage(self, reason: str = "manual stop") -> KillSwitchStatus:
        self._write(True, reason)
        return self.status()

    def release(self) -> KillSwitchStatus:
        self._write(False, None)
        return self.status()

    def _write(self, engaged: bool, reason: str | None) -> None:
        value = json.dumps({"engaged": engaged, "reason": reason}, ensure_ascii=False)
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO system_flags (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                               updated_at = excluded.updated_at
                """,
                (_KEY, value, time.time()),
            )
