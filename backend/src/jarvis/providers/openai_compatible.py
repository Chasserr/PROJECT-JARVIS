from __future__ import annotations

import httpx


class OpenAICompatibleProvider:
    """Adapter for LM Studio and Ollama's OpenAI-compatible chat endpoint."""

    def __init__(self, *, base_url: str, api_key: str, model: str,
                 timeout_seconds: float = 60.0, name: str = "local") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.name = name

    async def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.2,
                       max_tokens: int = 1200) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Provider returned an invalid chat-completion response.") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Provider returned an empty response.")
        return content.strip()
