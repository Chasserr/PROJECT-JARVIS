"""Encrypted long-term memory plus short-term episode history."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from ..db import Database
from ..security.crypto import SecretBox
from .embeddings import EmbeddingProvider
from .models import (
    Memory,
    MemoryCreate,
    MemoryKind,
    cosine,
    pack_vector,
    unpack_vector,
)

log = logging.getLogger(__name__)

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "i",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
    "you",
    "your",
}


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in _STOPWORDS
    ]


def lexical_score(query: str, content: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    content_tokens = set(_tokens(content))
    hits = sum(1 for token in query_tokens if token in content_tokens)
    return hits / len(query_tokens)


class MemoryStore:
    def __init__(
        self,
        db: Database,
        box: SecretBox,
        embeddings: EmbeddingProvider | None = None,
    ) -> None:
        self._db = db
        self._box = box
        self._embeddings = embeddings
        self._embedding_warned = False

    async def add(self, data: MemoryCreate, *, source: str = "user") -> Memory:
        now = time.time()
        memory_id = str(uuid.uuid4())
        vector: list[float] | None = None
        embedding_model: str | None = None
        if self._embeddings is not None:
            try:
                vector = await self._embeddings.embed(data.content)
                embedding_model = self._embeddings.model
            except Exception as exc:  # embedding is an enhancement, not a dependency
                self._warn_embedding(exc)
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO memories
                    (id, kind, content, tags, source, embedding, embedding_model,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    data.kind.value,
                    self._box.encrypt_text(data.content, context=b"memory"),
                    json.dumps(data.tags),
                    source,
                    pack_vector(vector) if vector is not None else None,
                    embedding_model,
                    now,
                    now,
                ),
            )
        return Memory(
            id=memory_id,
            kind=data.kind.value,
            content=data.content,
            tags=data.tags,
            source=source,
            created_at=now,
            updated_at=now,
        )

    def get(self, memory_id: str) -> Memory | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ? AND deleted_at IS NULL", (memory_id,)
            ).fetchone()
        return self._to_memory(row) if row else None

    def list(self, limit: int = 50, *, kind: str | None = None) -> list[Memory]:
        limit = max(1, min(limit, 500))
        query = "SELECT * FROM memories WHERE deleted_at IS NULL"
        params: list[Any] = []
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._to_memory(row) for row in rows]

    async def search(self, query: str, limit: int = 10) -> list[Memory]:
        query = query.strip()
        if not query:
            return self.list(limit)
        limit = max(1, min(limit, 50))
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE deleted_at IS NULL ORDER BY updated_at DESC"
            ).fetchall()
        if not rows:
            return []

        query_vector: list[float] | None = None
        if self._embeddings is not None:
            try:
                query_vector = await self._embeddings.embed(query)
            except Exception as exc:
                self._warn_embedding(exc)

        scored: list[tuple[float, Memory]] = []
        for row in rows:
            memory = self._to_memory(row)
            vector_score: float | None = None
            if (
                query_vector is not None
                and row["embedding"] is not None
                and row["embedding_model"] == self._embeddings.model
            ):
                vector_score = cosine(query_vector, unpack_vector(row["embedding"]))
            lexical = lexical_score(query, memory.content)
            # Blend so exact terms still matter when embeddings are noisy.
            score = lexical if vector_score is None else 0.75 * vector_score + 0.25 * lexical
            if score > 0:
                memory.score = round(score, 6)
                scored.append((score, memory))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [memory for _, memory in scored[:limit]]

    def delete(self, memory_id: str, *, hard: bool = False) -> bool:
        with self._db.connection() as conn:
            if hard:
                cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            else:
                cursor = conn.execute(
                    "UPDATE memories SET deleted_at = ?, updated_at = ? "
                    "WHERE id = ? AND deleted_at IS NULL",
                    (time.time(), time.time(), memory_id),
                )
        return cursor.rowcount > 0

    def count(self) -> int:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE deleted_at IS NULL"
            ).fetchone()
        return int(row["n"])

    def add_episode(
        self, session_id: str, role: str, content: str, meta: dict[str, Any] | None = None
    ) -> str:
        episode_id = str(uuid.uuid4())
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO episodes (id, session_id, role, content, created_at, meta)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    session_id,
                    role,
                    self._box.encrypt_text(content, context=b"episode"),
                    time.time(),
                    json.dumps(meta or {}),
                ),
            )
        return episode_id

    def episodes(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        result = []
        for row in reversed(rows):
            result.append(
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "role": row["role"],
                    "content": self._box.decrypt_text(row["content"], context=b"episode"),
                    "created_at": row["created_at"],
                    "meta": json.loads(row["meta"]),
                }
            )
        return result

    def _warn_embedding(self, exc: Exception) -> None:
        if self._embedding_warned:
            log.debug("embedding still unavailable: %s", exc)
        else:
            self._embedding_warned = True
            log.warning("embeddings unavailable; using lexical search: %s", exc)

    def _to_memory(self, row: Any) -> Memory:
        return Memory(
            id=row["id"],
            kind=row["kind"],
            content=self._box.decrypt_text(row["content"], context=b"memory"),
            tags=json.loads(row["tags"]),
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


__all__ = ["MemoryStore", "MemoryKind", "lexical_score"]
