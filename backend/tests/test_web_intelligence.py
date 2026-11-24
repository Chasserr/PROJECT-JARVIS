from __future__ import annotations

import pytest

from jarvis.skills.web_intelligence import (
    _SearchResults,
    _TextExtractor,
    _validate_public_url,
)


def test_blocks_local_and_private_targets() -> None:
    for url in (
        "http://127.0.0.1/",
        "http://localhost/",
        "http://192.168.1.10/",
        "http://169.254.169.254/latest/meta-data/",
        "file:///C:/Windows/win.ini",
    ):
        with pytest.raises(ValueError):
            _validate_public_url(url)


def test_rejects_embedded_credentials_and_nonstandard_ports() -> None:
    with pytest.raises(ValueError):
        _validate_public_url("https://user:pass@example.com/")
    with pytest.raises(ValueError):
        _validate_public_url("https://example.com:8443/")


def test_html_extractor_omits_script_and_style_content() -> None:
    parser = _TextExtractor()
    parser.feed(
        "<html><head><title>Example page</title><style>hidden css</style></head>"
        "<body><h1>Hello</h1><p>Useful content</p><script>secret()</script></body></html>"
    )
    assert parser.title == "Example page"
    assert "Hello" in parser.text
    assert "Useful content" in parser.text
    assert "hidden css" not in parser.text
    assert "secret()" not in parser.text


def test_search_parser_extracts_result_links() -> None:
    parser = _SearchResults()
    parser.feed(
        '<a class="result__a" href="https://example.org/article">Example Article</a>'
    )
    assert parser.results == [
        {"title": "Example Article", "url": "https://example.org/article"}
    ]
