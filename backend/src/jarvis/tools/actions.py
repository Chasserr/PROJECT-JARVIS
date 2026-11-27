"""Action tools: draft and send email, generate and save a report.

The two irreversible actions (sending mail, writing a report file) are
``PermissionTier.CONFIRM`` and ``dangerous``, so the registry pauses them for an
explicit approval before any side effect happens. Nothing here pretends to have
sent anything when SMTP is not configured.
"""

from __future__ import annotations

import re
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path
from typing import Any

from ..config import Settings
from ..security.permissions import PermissionTier
from .manifest import ToolManifest
from .registry import ToolContext, ToolRegistry, ToolResult

_EMAIL_RE = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[A-Za-z]{2,}$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _clean_address(value: str) -> str:
    _, address = parseaddr(value.strip())
    if not address or not _EMAIL_RE.match(address):
        raise ValueError(f"not a valid email address: {value!r}")
    return address


def _recipients(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = [item for item in re.split(r"[,;]", value) if item.strip()]
    else:
        parts = [str(item) for item in value]
    cleaned = [_clean_address(item) for item in parts]
    if not cleaned:
        raise ValueError("at least one recipient is required")
    if len(cleaned) > 20:
        raise ValueError("at most 20 recipients are allowed")
    return cleaned


def _draft(args: dict[str, Any], context: ToolContext) -> ToolResult:
    to = _recipients(args["to"])
    subject = str(args["subject"]).strip()
    body = str(args["body"]).strip()
    if not subject:
        return ToolResult(ok=False, error="subject must not be empty")
    if not body:
        return ToolResult(ok=False, error="body must not be empty")
    sender = context.settings.email_from or context.settings.email_user or ""
    signature = context.settings.email_signature.strip()
    rendered = body + (f"\n\n{signature}" if signature else "")
    return ToolResult(
        ok=True,
        output={
            "status": "draft",
            "from": sender or "(JARVIS_EMAIL_FROM not set)",
            "to": to,
            "subject": subject,
            "body": rendered,
            "sent": False,
            "note": (
                "This is a draft. Sending requires email.send, which pauses for "
                "explicit approval."
            ),
        },
    )


def _smtp_send(settings: Settings, message: EmailMessage) -> None:
    host = settings.email_smtp_host
    if not host or not settings.email_user or settings.email_password is None:
        raise RuntimeError(
            "SMTP is not configured: set JARVIS_EMAIL_SMTP_HOST, JARVIS_EMAIL_USER "
            "and JARVIS_EMAIL_PASSWORD"
        )
    context = ssl.create_default_context()
    if settings.email_smtp_ssl:
        with smtplib.SMTP_SSL(host, settings.email_smtp_port, timeout=30, context=context) as server:
            server.login(settings.email_user, settings.email_password.get_secret_value())
            server.send_message(message)
        return
    with smtplib.SMTP(host, settings.email_smtp_port, timeout=30) as server:
        server.ehlo()
        if settings.email_smtp_starttls:
            server.starttls(context=context)
            server.ehlo()
        server.login(settings.email_user, settings.email_password.get_secret_value())
        server.send_message(message)


def _send(args: dict[str, Any], context: ToolContext) -> ToolResult:
    settings = context.settings
    to = _recipients(args["to"])
    subject = str(args["subject"]).strip()
    body = str(args["body"]).strip()
    sender = settings.email_from or settings.email_user
    if not sender:
        return ToolResult(
            ok=False,
            error="no sender address: set JARVIS_EMAIL_FROM or JARVIS_EMAIL_USER",
        )
    signature = settings.email_signature.strip()
    message = EmailMessage()
    message["From"] = formataddr(("JARVIS", sender))
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body + (f"\n\n{signature}" if signature else ""))
    try:
        _smtp_send(settings, message)
    except (OSError, smtplib.SMTPException, RuntimeError) as exc:
        return ToolResult(ok=False, error=f"send failed: {type(exc).__name__}: {exc}")
    return ToolResult(
        ok=True,
        output={
            "status": "sent",
            "from": sender,
            "to": to,
            "subject": subject,
            "message_id": message.get("Message-ID", ""),
        },
    )


def _report(args: dict[str, Any], context: ToolContext) -> ToolResult:
    settings = context.settings
    title = str(args["title"]).strip()
    if not title:
        return ToolResult(ok=False, error="title must not be empty")
    sections = args.get("sections") or []
    if not isinstance(sections, list) or not sections:
        return ToolResult(ok=False, error="at least one section is required")
    stamp = datetime.now(UTC)
    lines = [f"# {title}", "", f"_Generated {stamp.isoformat(timespec='seconds')} by JARVIS_", ""]
    for section in sections:
        heading = str(section.get("heading", "")).strip() or "Section"
        body = str(section.get("body", "")).strip()
        lines.extend([f"## {heading}", "", body, ""])
    sources = args.get("sources") or []
    if sources:
        lines.extend(["## Sources", ""])
        for item in sources:
            lines.append(f"- {item}")
        lines.append("")
    markdown = "\n".join(lines)
    base = settings.reports_dir or (settings.data_dir / "reports")
    directory = Path(base)
    directory.mkdir(parents=True, exist_ok=True)
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")[:60] or "report"
    path = directory / f"{slug}-{stamp.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(markdown, encoding="utf-8")
    return ToolResult(
        ok=True,
        output={
            "status": "saved",
            "path": str(path),
            "bytes": len(markdown.encode("utf-8")),
            "sections": len(sections),
        },
    )


def register_action_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolManifest(
            name="email.draft",
            description=(
                "Compose an email draft (recipients, subject, body) without sending it. "
                "Use this first so the user can review the exact text."
            ),
            permission=PermissionTier.READ_ONLY,
            input_schema={
                "type": "object",
                "properties": {
                    "to": {
                        "oneOf": [
                            {"type": "string", "maxLength": 1000},
                            {
                                "type": "array",
                                "items": {"type": "string", "maxLength": 320},
                                "maxItems": 20,
                            },
                        ]
                    },
                    "subject": {"type": "string", "minLength": 1, "maxLength": 300},
                    "body": {"type": "string", "minLength": 1, "maxLength": 20_000},
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": False,
            },
            tags=["email", "draft"],
        ),
        _draft,
    )
    registry.register(
        ToolManifest(
            name="email.send",
            description=(
                "Send an email through the configured SMTP account. This is an external "
                "communication and always pauses for explicit user approval."
            ),
            permission=PermissionTier.CONFIRM,
            dangerous=True,
            input_schema={
                "type": "object",
                "properties": {
                    "to": {
                        "oneOf": [
                            {"type": "string", "maxLength": 1000},
                            {
                                "type": "array",
                                "items": {"type": "string", "maxLength": 320},
                                "maxItems": 20,
                            },
                        ]
                    },
                    "subject": {"type": "string", "minLength": 1, "maxLength": 300},
                    "body": {"type": "string", "minLength": 1, "maxLength": 20_000},
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": False,
            },
            timeout_s=60,
            tags=["email", "external", "communication"],
        ),
        _send,
    )
    registry.register(
        ToolManifest(
            name="report.generate",
            description=(
                "Write a Markdown report from titled sections and save it to the reports "
                "folder. Returns the real path and byte count."
            ),
            permission=PermissionTier.CONFIRM,
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 200},
                    "sections": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 30,
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string", "minLength": 1, "maxLength": 200},
                                "body": {"type": "string", "maxLength": 20_000},
                            },
                            "required": ["heading"],
                            "additionalProperties": False,
                        },
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 2000},
                        "maxItems": 50,
                    },
                },
                "required": ["title", "sections"],
                "additionalProperties": False,
            },
            tags=["report", "file", "documentation"],
        ),
        _report,
    )


__all__ = ["register_action_tools"]
