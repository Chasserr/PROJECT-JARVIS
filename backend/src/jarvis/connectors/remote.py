"""Remote connectors: web, GitHub, Supabase, email (IMAP, read-only).

Each one reports ``not_configured`` until its credentials exist. None of them
holds a hard-coded endpoint that could reach a private address by default, and
none writes anything to the remote service.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import email
import imaplib
from email.header import decode_header, make_header
from typing import Any

import httpx

from ..config import Settings
from ..skills.web_read import read_url
from ..skills.web_search import brave_search
from .base import Connector, SourceError, SourceHit, SourceState, SourceStatus


class WebConnector(Connector):
    """Brave web search plus the SSRF-guarded page reader."""

    id = "web"
    label = "Web"
    kind = "remote"
    scopes = ("read", "search")
    requires = ("JARVIS_BRAVE_API_KEY",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def status(self) -> SourceStatus:
        if self._settings.brave_api_key is None:
            return SourceStatus(
                SourceState.NOT_CONFIGURED, "set JARVIS_BRAVE_API_KEY to enable web search"
            )
        return SourceStatus(SourceState.CONNECTED, "Brave Search key is configured")

    async def search(self, query: str, *, limit: int) -> list[SourceHit]:
        results = await brave_search(
            query, count=min(limit, 10), settings=self._settings
        )
        return [
            SourceHit(
                source=self.id,
                title=item["title"] or item["url"],
                locator=item["url"],
                snippet=item["description"],
                metadata={"url": item["url"]},
            )
            for item in results
        ]

    async def read(self, locator: str, *, max_chars: int) -> dict[str, Any]:
        result = await read_url(locator, settings=self._settings, max_chars=max_chars)
        return {
            "title": result["url"],
            "locator": result["url"],
            "text": result["text"],
            "truncated": result["truncated"],
            "status": result["status"],
            "content_type": result["content_type"],
        }


class GitHubConnector(Connector):
    """Repository search and file reads through the GitHub REST API."""

    id = "github"
    label = "GitHub"
    kind = "remote"
    scopes = ("read", "search")
    requires = ("JARVIS_GITHUB_TOKEN",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _token(self) -> str | None:
        return (
            self._settings.github_token.get_secret_value()
            if self._settings.github_token is not None
            else None
        )

    def status(self) -> SourceStatus:
        if not self._token():
            return SourceStatus(
                SourceState.NOT_CONFIGURED, "set JARVIS_GITHUB_TOKEN to authorise GitHub"
            )
        return SourceStatus(SourceState.CONNECTED, "token configured (read-only scopes expected)")

    def _headers(self) -> dict[str, str]:
        token = self._token()
        if not token:
            raise SourceError("GitHub token is not configured")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def search(self, query: str, *, limit: int) -> list[SourceHit]:
        base = self._settings.github_api_url.rstrip("/")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{base}/search/repositories",
                params={"q": query, "per_page": min(limit, 20)},
                headers=self._headers(),
            )
            response.raise_for_status()
            items = response.json().get("items", [])
        return [
            SourceHit(
                source=self.id,
                title=str(item.get("full_name", "")),
                locator=str(item.get("full_name", "")),
                snippet=str(item.get("description") or "")[:400],
                metadata={
                    "url": item.get("html_url"),
                    "stars": item.get("stargazers_count"),
                    "private": item.get("private"),
                    "updated": item.get("updated_at"),
                },
            )
            for item in items[:limit]
        ]

    async def read(self, locator: str, *, max_chars: int) -> dict[str, Any]:
        """``locator`` is ``owner/repo/path/to/file``."""
        parts = [part for part in locator.strip().split("/") if part]
        if len(parts) < 3:
            raise SourceError("GitHub locator must look like owner/repo/path/to/file")
        owner, repo = parts[0], parts[1]
        path = "/".join(parts[2:])
        base = self._settings.github_api_url.rstrip("/")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{base}/repos/{owner}/{repo}/contents/{path}",
                headers=self._headers(),
            )
            if response.status_code == 404:
                raise SourceError(f"not found: {owner}/{repo}/{path}")
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, list):
            raise SourceError("locator points at a directory, not a file")
        content = payload.get("content", "")
        try:
            text = base64.b64decode(content).decode("utf-8", errors="replace")
        except (ValueError, TypeError) as exc:
            raise SourceError(f"could not decode file content: {exc}") from exc
        return {
            "title": payload.get("name", path),
            "locator": f"{owner}/{repo}/{path}",
            "text": text[:max_chars],
            "truncated": len(text) > max_chars,
            "url": payload.get("html_url"),
        }


class SupabaseConnector(Connector):
    """Read-only PostgREST access to explicitly listed tables."""

    id = "supabase"
    label = "Supabase"
    kind = "remote"
    scopes = ("read", "search")
    requires = ("JARVIS_SUPABASE_URL", "JARVIS_SUPABASE_KEY", "JARVIS_SUPABASE_TABLES")

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def status(self) -> SourceStatus:
        missing = [
            name
            for name, value in (
                ("JARVIS_SUPABASE_URL", self._settings.supabase_url),
                ("JARVIS_SUPABASE_KEY", self._settings.supabase_key),
            )
            if not value
        ]
        if not self._settings.supabase_tables:
            missing.append("JARVIS_SUPABASE_TABLES")
        if missing:
            return SourceStatus(
                SourceState.NOT_CONFIGURED, "set " + ", ".join(missing)
            )
        return SourceStatus(
            SourceState.CONNECTED,
            f"{len(self._settings.supabase_tables)} table(s) authorised",
        )

    def _headers(self) -> dict[str, str]:
        key = (
            self._settings.supabase_key.get_secret_value()
            if self._settings.supabase_key is not None
            else ""
        )
        if not self._settings.supabase_url or not key:
            raise SourceError("Supabase URL or key is not configured")
        return {"apikey": key, "Authorization": f"Bearer {key}"}

    async def search(self, query: str, *, limit: int) -> list[SourceHit]:
        base = (self._settings.supabase_url or "").rstrip("/")
        needle = query.strip().lower()
        hits: list[SourceHit] = []
        headers = self._headers()
        async with httpx.AsyncClient(timeout=15.0) as client:
            for table in self._settings.supabase_tables:
                response = await client.get(
                    f"{base}/rest/v1/{table}",
                    params={"select": "*", "limit": 200},
                    headers=headers,
                )
                if response.status_code >= 400:
                    raise SourceError(
                        f"table '{table}' returned {response.status_code}: {response.text[:200]}"
                    )
                for row in response.json() or []:
                    if not isinstance(row, dict):
                        continue
                    blob = " ".join(str(value) for value in row.values())
                    if needle not in blob.lower():
                        continue
                    label = str(
                        row.get("title") or row.get("name") or row.get("id") or "row"
                    )
                    hits.append(
                        SourceHit(
                            source=self.id,
                            title=f"{table}/{label}",
                            locator=f"{table}/{row.get('id', label)}",
                            snippet=blob[:300],
                            metadata={"table": table},
                        )
                    )
                    if len(hits) >= limit:
                        return hits
        return hits

    async def read(self, locator: str, *, max_chars: int) -> dict[str, Any]:
        if "/" not in locator:
            raise SourceError("Supabase locator must look like table/id")
        table, row_id = locator.split("/", 1)
        if table not in self._settings.supabase_tables:
            raise SourceError(f"table '{table}' is not authorised")
        base = (self._settings.supabase_url or "").rstrip("/")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{base}/rest/v1/{table}",
                params={"select": "*", "id": f"eq.{row_id}", "limit": 1},
                headers=self._headers(),
            )
            response.raise_for_status()
            rows = response.json() or []
        if not rows:
            raise SourceError(f"no row {row_id} in {table}")
        import json

        text = json.dumps(rows[0], indent=2, default=str)
        return {
            "title": f"{table}/{row_id}",
            "locator": locator,
            "text": text[:max_chars],
            "truncated": len(text) > max_chars,
        }


class EmailConnector(Connector):
    """Read-only IMAP search. Sending lives in ``jarvis.tools.actions``."""

    id = "email"
    label = "Email (IMAP)"
    kind = "remote"
    scopes = ("read", "search")
    requires = ("JARVIS_EMAIL_IMAP_HOST", "JARVIS_EMAIL_USER", "JARVIS_EMAIL_PASSWORD")

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def status(self) -> SourceStatus:
        missing = [
            name
            for name, value in (
                ("JARVIS_EMAIL_IMAP_HOST", self._settings.email_imap_host),
                ("JARVIS_EMAIL_USER", self._settings.email_user),
                ("JARVIS_EMAIL_PASSWORD", self._settings.email_password),
            )
            if not value
        ]
        if missing:
            return SourceStatus(SourceState.NOT_CONFIGURED, "set " + ", ".join(missing))
        return SourceStatus(
            SourceState.CONNECTED, f"IMAP {self._settings.email_imap_host} (read-only)"
        )

    def _connect(self) -> imaplib.IMAP4:
        host = self._settings.email_imap_host
        if not host or not self._settings.email_user or self._settings.email_password is None:
            raise SourceError("email credentials are not configured")
        client: imaplib.IMAP4
        if self._settings.email_imap_ssl:
            client = imaplib.IMAP4_SSL(host, self._settings.email_imap_port)
        else:
            client = imaplib.IMAP4(host, self._settings.email_imap_port)
        client.login(
            self._settings.email_user,
            self._settings.email_password.get_secret_value(),
        )
        return client

    async def search(self, query: str, *, limit: int) -> list[SourceHit]:
        return await asyncio.to_thread(self._search_sync, query, limit)

    def _search_sync(self, query: str, limit: int) -> list[SourceHit]:
        client = self._connect()
        try:
            client.select("INBOX", readonly=True)
            # IMAP search takes a charset and a criterion; quoting happens in the
            # protocol layer, so a query cannot break out of the string.
            typ, data = client.search(None, "OR", "SUBJECT", f'"{query}"', "BODY", f'"{query}"')
            if typ != "OK":
                raise SourceError("IMAP search was rejected")
            ids = (data[0] or b"").split()[-limit:]
            hits: list[SourceHit] = []
            for message_id in reversed(ids):
                typ, payload = client.fetch(message_id, "(RFC822)")
                if typ != "OK" or not payload or not payload[0]:
                    continue
                raw = payload[0][1]
                message = email.message_from_bytes(raw)  # type: ignore[arg-type]
                subject = str(make_header(decode_header(message.get("Subject", ""))))
                sender = str(make_header(decode_header(message.get("From", ""))))
                body = ""
                if message.is_multipart():
                    for part in message.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode("utf-8", "replace")
                            break
                else:
                    decoded = message.get_payload(decode=True)
                    if isinstance(decoded, bytes):
                        body = decoded.decode("utf-8", "replace")
                hits.append(
                    SourceHit(
                        source=self.id,
                        title=subject or "(no subject)",
                        locator=f"imap:{message_id.decode() if isinstance(message_id, bytes) else message_id}",
                        snippet=" ".join(body.split())[:300],
                        metadata={"from": sender, "date": message.get("Date", "")},
                    )
                )
            return hits
        finally:
            with contextlib.suppress(imaplib.IMAP4.error):
                client.logout()


__all__ = [
    "EmailConnector",
    "GitHubConnector",
    "SupabaseConnector",
    "WebConnector",
]
