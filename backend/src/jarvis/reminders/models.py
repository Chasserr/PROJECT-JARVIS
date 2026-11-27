"""Reminder models. Text is encrypted before it touches SQLite."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReminderCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    due_at: float | None = None


class Reminder(BaseModel):
    id: str
    text: str
    due_at: float | None
    status: str = "pending"
    created_at: float
    updated_at: float
