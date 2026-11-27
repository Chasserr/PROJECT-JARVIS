"""Anthropic Messages API client. Cloud calls are opt-in twice: provider + allow_cloud."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from .base import LLMError, LLMResponse, Message, Role, ToolCall


class AnthropicClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        allow_cloud: bool = False,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.allow_cloud = allow_cloud
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
        if not self.allow_cloud:
            raise LLMError("cloud calls are disabled; set JARVIS_ALLOW_CLOUD=true to opt in")
        if not self.api_key:
            raise LLMError("ANTHROPIC_API_KEY is not configured")

        system_parts = [m.content for m in messages if m.role is Role.SYSTEM]
        conversation = [
            {"role": m.role.value, "content": m.content}
            for m in messages
            if m.role in (Role.USER, Role.ASSISTANT)
        ]
        if not conversation:
            conversation = [{"role": "user", "content": "Continue."}]

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conversation,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool["parameters"],
                }
                for tool in tools
            ]

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages", json=payload, headers=headers
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"Anthropic returned {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in body.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        id=block.get("id") or str(uuid.uuid4()),
                        name=block.get("name", ""),
                        arguments=block.get("input") or {},
                    )
                )
        return LLMResponse(
            text="\n".join(part for part in text_parts if part),
            tool_calls=calls,
            model=body.get("model", self.model),
            raw=body,
        )
