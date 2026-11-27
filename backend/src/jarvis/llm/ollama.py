"""Ollama client using its native /api/chat endpoint."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from .base import LLMError, LLMResponse, Message, ToolCall


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float = 120.0,
        think: bool | None = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout
        self._think = think

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
            "messages": [
                message.model_dump(exclude_none=True, mode="json") for message in messages
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
        if json_mode:
            payload["format"] = "json"
        if self._think is not None:
            payload["think"] = self._think

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise LLMError(
                f"Ollama returned {exc.response.status_code}: {detail}. "
                f"Is model '{self.model}' pulled?"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Ollama is unreachable at {self.base_url}: {exc}. Start `ollama serve`."
            ) from exc
        except ValueError as exc:
            raise LLMError("Ollama returned invalid JSON") from exc

        message = body.get("message") or {}
        calls: list[ToolCall] = []
        for raw_call in message.get("tool_calls") or []:
            function = raw_call.get("function") or {}
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(
                ToolCall(
                    id=raw_call.get("id") or str(uuid.uuid4()),
                    name=function.get("name", ""),
                    arguments=arguments,
                )
            )
        return LLMResponse(
            text=message.get("content") or message.get("thinking") or "",
            tool_calls=calls,
            model=body.get("model", self.model),
            raw=body,
        )

    async def available_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"cannot list Ollama models: {exc}") from exc
        return [item.get("name", "") for item in body.get("models", []) if item.get("name")]
