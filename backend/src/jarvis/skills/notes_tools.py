"""Tool bodies for the notes.* skills."""

from __future__ import annotations

from typing import Any

from ..notes.models import NoteCreate, NoteUpdate
from ..notes.store import NoteStore
from ..tools.registry import ToolContext


def _store(context: ToolContext) -> NoteStore:
    if context.db is None or context.box is None:
        raise RuntimeError("notes require database and encryption context")
    return NoteStore(context.db, context.box)


def create_note(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    note = _store(context).add(
        NoteCreate(
            title=args.get("title", ""),
            body=args["body"],
            tags=args.get("tags", []),
        ),
        source=context.actor,
    )
    return note.model_dump()


def list_notes(args: dict[str, Any], context: ToolContext) -> list[dict[str, Any]]:
    notes = _store(context).list(args.get("limit", 20))
    return [note.model_dump() for note in notes]


def update_note(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    note = _store(context).update(
        args["id"],
        NoteUpdate(
            title=args.get("title"),
            body=args.get("body"),
            tags=args.get("tags"),
        ),
    )
    return note.model_dump()


def delete_note(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    deleted = _store(context).delete(args["id"], hard=args.get("hard", False))
    return {"deleted": deleted, "id": args["id"]}


__all__ = ["create_note", "delete_note", "list_notes", "update_note"]
