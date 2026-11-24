from __future__ import annotations

import httpx


class ClaudeProvider:
    """Anthropic Messages API adapter. The API key is never included in errors or logs."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Claude API key is required when cloud inference is enabled.")
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self.name = "claude"

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> str:
        system_messages = [
            item["content"] for item in messages if item.get("role") == "system"
        ]
        conversation = [
            {"role": item["role"], "content": item["content"]}
            for item in messages
            if item.get("role") in {"user", "assistant"}
        ]
        if not conversation:
            raise ValueError("Claude requires at least one user or assistant message.")
        payload: dict[str, object] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conversation,
        }
        if system_messages:
            payload["system"] = "\n\n".join(system_messages)
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, transport=self._transport
        ) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise TypeError("Claude returned an invalid Messages API response.")
        text_blocks = [
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "\n".join(part for part in text_blocks if isinstance(part, str)).strip()
        if not content:
            raise ValueError("Claude returned an empty response.")
        return content
