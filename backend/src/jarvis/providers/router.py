from __future__ import annotations

import httpx

from jarvis.providers.base import ChatProvider


class FallbackProvider:
    """Try the configured primary provider, then fall back to local inference."""

    def __init__(self, primary: ChatProvider, fallback: ChatProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}_with_{fallback.name}_fallback"
        self.last_provider = primary.name

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> str:
        try:
            result = await self.primary.complete(
                messages, temperature=temperature, max_tokens=max_tokens
            )
            self.last_provider = self.primary.name
            return result
        except (httpx.HTTPError, ValueError, RuntimeError) as primary_error:
            try:
                result = await self.fallback.complete(
                    messages, temperature=temperature, max_tokens=max_tokens
                )
                self.last_provider = self.fallback.name
                return result
            except (httpx.HTTPError, ValueError, RuntimeError) as fallback_error:
                raise RuntimeError(
                    "Primary and fallback AI providers are unavailable "
                    f"({type(primary_error).__name__}; {type(fallback_error).__name__})."
                ) from fallback_error
