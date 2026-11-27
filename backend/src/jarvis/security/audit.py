"""Append-only, hash-chained audit log with encrypted detail payloads."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..db import Database
from .crypto import SecretBox

GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    id: str
    ts: float
    actor: str
    action: str
    tool: str | None
    permission: str | None
    outcome: str
    detail: Any | None
    prev_hash: str
    entry_hash: str


@dataclass(frozen=True)
class AuditVerification:
    ok: bool
    checked: int
    first_bad_seq: int | None = None
    message: str = "chain intact"


def _hash_entry(
    *,
    ts: float,
    actor: str,
    action: str,
    tool: str | None,
    permission: str | None,
    outcome: str,
    detail_hash: str,
    prev_hash: str,
) -> str:
    material = "|".join(
        [
            f"{ts:.6f}",
            actor,
            action,
            tool or "",
            permission or "",
            outcome,
            detail_hash,
            prev_hash,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, db: Database, box: SecretBox) -> None:
        self._db = db
        self._box = box

    def record(
        self,
        *,
        actor: str,
        action: str,
        outcome: str = "ok",
        tool: str | None = None,
        permission: str | None = None,
        detail: Any | None = None,
    ) -> AuditEntry:
        ts = time.time()
        entry_id = str(uuid.uuid4())
        detail_blob = (
            self._box.encrypt_json(detail, context=b"audit") if detail is not None else None
        )
        detail_hash = hashlib.sha256(detail_blob).hexdigest() if detail_blob is not None else ""
        with self._db.connection() as conn:
            row = conn.execute("SELECT entry_hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev_hash = row["entry_hash"] if row else GENESIS
            entry_hash = _hash_entry(
                ts=ts,
                actor=actor,
                action=action,
                tool=tool,
                permission=permission,
                outcome=outcome,
                detail_hash=detail_hash,
                prev_hash=prev_hash,
            )
            conn.execute(
                """
                INSERT INTO audit
                    (id, ts, actor, action, tool, permission, outcome, detail, prev_hash, entry_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    ts,
                    actor,
                    action,
                    tool,
                    permission,
                    outcome,
                    detail_blob,
                    prev_hash,
                    entry_hash,
                ),
            )
            seq = conn.execute("SELECT seq FROM audit WHERE id = ?", (entry_id,)).fetchone()["seq"]
        return AuditEntry(
            seq=seq,
            id=entry_id,
            ts=ts,
            actor=actor,
            action=action,
            tool=tool,
            permission=permission,
            outcome=outcome,
            detail=detail,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )

    def tail(self, limit: int = 50) -> list[AuditEntry]:
        limit = max(1, min(limit, 500))
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._to_entry(row) for row in reversed(rows)]

    def verify(self) -> AuditVerification:
        with self._db.connection() as conn:
            rows = conn.execute("SELECT * FROM audit ORDER BY seq ASC").fetchall()
        prev = GENESIS
        for index, row in enumerate(rows, start=1):
            detail_blob = row["detail"]
            detail_hash = hashlib.sha256(detail_blob).hexdigest() if detail_blob is not None else ""
            expected = _hash_entry(
                ts=row["ts"],
                actor=row["actor"],
                action=row["action"],
                tool=row["tool"],
                permission=row["permission"],
                outcome=row["outcome"],
                detail_hash=detail_hash,
                prev_hash=prev,
            )
            if row["prev_hash"] != prev or row["entry_hash"] != expected:
                return AuditVerification(
                    ok=False,
                    checked=index,
                    first_bad_seq=row["seq"],
                    message=f"audit chain mismatch at seq {row['seq']}",
                )
            prev = row["entry_hash"]
        return AuditVerification(ok=True, checked=len(rows))

    def _to_entry(self, row: Any) -> AuditEntry:
        detail = None
        if row["detail"] is not None:
            try:
                detail = self._box.decrypt_json(row["detail"], context=b"audit")
            except Exception:
                detail = {"error": "detail could not be decrypted"}
        return AuditEntry(
            seq=row["seq"],
            id=row["id"],
            ts=row["ts"],
            actor=row["actor"],
            action=row["action"],
            tool=row["tool"],
            permission=row["permission"],
            outcome=row["outcome"],
            detail=detail,
            prev_hash=row["prev_hash"],
            entry_hash=row["entry_hash"],
        )


def detail_preview(detail: Any, limit: int = 200) -> str:
    """Stable compact rendering used in logs and CLI output."""
    text = json.dumps(detail, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"
