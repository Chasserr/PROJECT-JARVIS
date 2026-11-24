from __future__ import annotations

from typing import Protocol


class ChatProvider(Protocol):
    name: str

    async def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.2,
                       max_tokens: int = 1200) -> str: ...
