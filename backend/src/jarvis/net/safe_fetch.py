"""SSRF-safe URL validation and bounded HTML-to-text extraction."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

Resolver = Callable[[str, int], list[str]]

_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
_ACTIVE_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "object",
    "embed",
    "svg",
    "math",
    "canvas",
}
_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
_TEXT_CONTENT_TYPES = ("text/", "application/xhtml+xml", "application/json", "application/xml")


class UnsafeURLError(ValueError):
    """Raised when a URL could reach a private, local, or non-HTTP target."""


@dataclass(frozen=True)
class ParsedURL:
    scheme: str
    host: str
    port: int
    url: str


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    content_type: str
    text: str
    truncated: bool


def _default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def _reject_ip(raw: str) -> None:
    try:
        address = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError as exc:
        raise UnsafeURLError(f"could not interpret address: {raw}") from exc
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise UnsafeURLError(f"address is not publicly routable: {address}")


def validate_url(url: str, *, resolver: Resolver | None = None) -> ParsedURL:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeURLError(f"malformed URL: {exc}") from exc
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"scheme must be http or https: {parsed.scheme or '<none>'}")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("URLs with embedded credentials are not allowed")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURLError("URL has no host")
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeURLError(f"host is not allowed: {host}")
    effective_port = port if port is not None else (443 if parsed.scheme.lower() == "https" else 80)
    if effective_port <= 0 or effective_port > 65535:
        raise UnsafeURLError(f"port is out of range: {effective_port}")

    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        pass
    else:
        _reject_ip(host)
    if resolver is not None:
        try:
            addresses = resolver(host, effective_port)
        except OSError as exc:
            raise UnsafeURLError(f"could not resolve host: {host}") from exc
        if not addresses:
            raise UnsafeURLError(f"host did not resolve: {host}")
        for address in addresses:
            _reject_ip(address)
    return ParsedURL(
        scheme=parsed.scheme.lower(), host=host, port=effective_port, url=parsed.geturl()
    )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _ACTIVE_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _ACTIVE_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self._parts).splitlines())
        return "\n".join(line for line in lines if line)


def extract_text(html: str, *, max_chars: int = 20_000) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = parser.text()
    return text[: max(0, max_chars)]


def _is_text(content_type: str) -> bool:
    lowered = content_type.lower()
    return any(lowered.startswith(prefix) for prefix in _TEXT_CONTENT_TYPES)


async def fetch_text(
    url: str,
    *,
    max_bytes: int = 1_000_000,
    max_chars: int = 20_000,
    timeout: float = 15.0,
    max_redirects: int = 5,
    client: httpx.AsyncClient | None = None,
    resolver: Resolver = _default_resolver,
) -> FetchResult:
    """Fetch a public HTTP(S) URL, following redirects only after re-validating each hop."""

    own_client = client is None
    active = client or httpx.AsyncClient(timeout=timeout)
    current = url
    try:
        for _ in range(max_redirects + 1):
            validate_url(current, resolver=resolver)
            async with active.stream(
                "GET",
                current,
                headers={"User-Agent": "JARVIS/0.1 (local assistant)"},
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeURLError("redirect response had no location")
                    current = urljoin(str(response.url), location)
                    continue
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                chunks: list[bytes] = []
                total = 0
                truncated = False
                async for chunk in response.aiter_bytes():
                    remaining = max_bytes - total
                    if remaining <= 0:
                        truncated = True
                        break
                    if len(chunk) > remaining:
                        chunks.append(chunk[:remaining])
                        total = max_bytes
                        truncated = True
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                body = b"".join(chunks)
                encoding = response.encoding or "utf-8"
                raw = body.decode(encoding, errors="replace")
                text = extract_text(raw, max_chars=max_chars) if _is_text(content_type) else ""
                return FetchResult(
                    url=str(response.url),
                    status=response.status_code,
                    content_type=content_type,
                    text=text,
                    truncated=truncated,
                )
        raise UnsafeURLError(f"too many redirects (>{max_redirects})")
    finally:
        if own_client:
            await active.aclose()


__all__ = [
    "FetchResult",
    "ParsedURL",
    "UnsafeURLError",
    "extract_text",
    "fetch_text",
    "validate_url",
]
