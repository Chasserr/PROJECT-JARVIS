"""URL safety and HTML extraction used by web.read."""

from __future__ import annotations

import httpx
import pytest

from jarvis.net.safe_fetch import (
    UnsafeURLError,
    extract_text,
    fetch_text,
    validate_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "http://localhost/admin",
        "http://127.0.0.1:8766/health",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://192.168.1.10/",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
        "http://user:pass@example.com/",
        "http://example.com:0/",
    ],
)
def test_validate_url_blocks_unsafe_targets(url: str) -> None:
    with pytest.raises(UnsafeURLError):
        validate_url(url)


def test_validate_url_accepts_public_https() -> None:
    parsed = validate_url("https://example.com/docs?q=1")
    assert parsed.host == "example.com"
    assert parsed.scheme == "https"


def test_extract_text_drops_active_content_and_caps() -> None:
    html = """
    <html><head><style>.x{color:red}</style><script>alert('x')</script></head>
    <body><h1>Hello</h1><p>Readable&nbsp;text.</p>
    <noscript>hidden</noscript><div>Tail</div></body></html>
    """
    text = extract_text(html, max_chars=200)
    assert "Hello" in text
    assert "Readable text." in text
    assert "Tail" in text
    assert "alert" not in text
    assert "color:red" not in text
    assert "hidden" not in text

    capped = extract_text("<p>" + "a" * 500 + "</p>", max_chars=50)
    assert len(capped) == 50


async def test_fetch_text_rejects_redirect_to_private_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, text="should not be reached")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(UnsafeURLError):
            await fetch_text(
                "https://example.com/start",
                client=client,
                resolver=lambda host, port: ["93.184.216.34"],
            )


async def test_fetch_text_returns_readable_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><body><script>bad()</script><p>Good content</p></body></html>",
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_text(
            "https://example.com/page",
            client=client,
            resolver=lambda host, port: ["93.184.216.34"],
        )

    assert result.status == 200
    assert "Good content" in result.text
    assert "bad()" not in result.text
    assert result.truncated is False
