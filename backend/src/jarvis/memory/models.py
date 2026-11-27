"""Memory records and vector helpers."""

from __future__ import annotations

from array import array
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    NOTE = "note"
    EPISODE = "episode"


class Memory(BaseModel):
    id: str
    kind: str
    content: str
    tags: list[str] = Field(default_factory=list)
    source: str = "user"
    created_at: float
    updated_at: float
    score: float | None = None


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    kind: MemoryKind = MemoryKind.FACT
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("content")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be blank")
        return value

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        return sorted({tag.strip().lower() for tag in value if tag.strip()})[:20]


def pack_vector(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return values.tolist()


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
