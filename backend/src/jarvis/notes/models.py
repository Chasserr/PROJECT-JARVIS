"""Note models. Bodies are encrypted before they touch SQLite."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned = [tag.strip() for tag in tags if tag.strip()]
    if len(cleaned) > 20:
        raise ValueError("at most 20 tags are allowed")
    if any(len(tag) > 40 for tag in cleaned):
        raise ValueError("tags must be 40 characters or fewer")
    return cleaned


class NoteCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    tags: list[str] = Field(default_factory=list)

    _tags = field_validator("tags")(_clean_tags)


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    tags: list[str] | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str] | None) -> list[str] | None:
        return _clean_tags(value) if value is not None else None


class Note(BaseModel):
    id: str
    title: str
    body: str
    tags: list[str]
    created_at: float
    updated_at: float
