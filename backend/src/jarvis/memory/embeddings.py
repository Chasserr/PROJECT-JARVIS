"""Embedding providers. Ollama is optional; memory search falls back to lexical."""

from __future__ import annotations

from typing import Protocol

import httpx


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    model: str

    async def embed(self, text: str) -> list[float]: ...


class OllamaEmbeddings:
    def __init__(self, base_url: str, model: str, *, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout

    async def embed(self, text: str) -> list[float]:
        payload = {"model": self.model, "input": text}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self.base_url}/api/embed", json=payload)
            if response.status_code == 404:
                # Older Ollama releases expose /api/embeddings with a prompt key.
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
            if response.status_code == 404:
                raise EmbeddingError(
                    f"embedding model '{self.model}' is not installed; "
                    f"run `ollama pull {self.model}`"
                )
            response.raise_for_status()
            body = response.json()
        if "embeddings" in body and body["embeddings"]:
            return [float(value) for value in body["embeddings"][0]]
        if "embedding" in body:
            return [float(value) for value in body["embedding"]]
        raise EmbeddingError("Ollama returned no embedding")
