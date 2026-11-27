"""Tool bodies for the reminders.* skills."""

from __future__ import annotations

from typing import Any

from ..reminders.models import ReminderCreate
from ..reminders.store import ReminderStore
from ..tools.registry import ToolContext


def _store(context: ToolContext) -> ReminderStore:
    if context.db is None or context.box is None:
        raise RuntimeError("reminders require database and encryption context")
    return ReminderStore(context.db, context.box)


def create_reminder(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    reminder = _store(context).add(ReminderCreate(text=args["text"], due_at=args.get("due_at")))
    return reminder.model_dump()


def list_reminders(args: dict[str, Any], context: ToolContext) -> list[dict[str, Any]]:
    reminders = _store(context).list(
        status=args.get("status"),
        limit=args.get("limit", 50),
    )
    return [reminder.model_dump() for reminder in reminders]


def complete_reminder(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    reminder = _store(context).complete(args["id"])
    return reminder.model_dump()


def delete_reminder(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    deleted = _store(context).delete(args["id"], hard=args.get("hard", False))
    return {"deleted": deleted, "id": args["id"]}


__all__ = ["complete_reminder", "create_reminder", "delete_reminder", "list_reminders"]
