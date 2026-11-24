import json

import httpx
import pytest

from jarvis.providers.claude import ClaudeProvider


async def test_claude_adapter_maps_system_messages_to_anthropic_field():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Claude says hello."}]},
        )

    provider = ClaudeProvider(
        api_key="test-secret",
        model="claude-sonnet-test",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.complete([
        {"role": "system", "content": "Follow safety rules."},
        {"role": "user", "content": "Hello"},
    ])

    assert result == "Claude says hello."
    assert captured["body"]["system"] == "Follow safety rules."
    assert captured["body"]["messages"] == [{"role": "user", "content": "Hello"}]
    assert captured["headers"]["x-api-key"] == "test-secret"


def test_claude_adapter_requires_key():
    with pytest.raises(ValueError, match="API key is required"):
        ClaudeProvider(api_key="", model="claude-sonnet-test")
