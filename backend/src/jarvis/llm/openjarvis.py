"""OpenJarvis OpenAI-compatible client for the specialist-agent planner."""

from __future__ import annotations

from typing import Any

import httpx

from .base import LLMError, LLMResponse, Message


class OpenJarvisClient:
    def __init__(self, base_url: str, model: str, *, timeout: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.model_dump(exclude_none=True, mode="json") for message in messages],
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self.base_url + "/v1/chat/completions", json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"OpenJarvis returned {exc.response.status_code}: {exc.response.text[:500]}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"OpenJarvis is unreachable at {self.base_url}: {exc}") from exc

        choices = body.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        text = message.get("content") or ""
        if isinstance(text, list):
            text = "".join(str(part.get("text", "")) for part in text if isinstance(part, dict))
        return LLMResponse(text=str(text), model=body.get("model", self.model), raw=body)
