"""LLM provider selection."""

from __future__ import annotations

import os

from ..config import Settings
from .anthropic import AnthropicClient
from .base import LLMClient, LLMError
from .ollama import OllamaClient
from .openjarvis import OpenJarvisClient


def build_llm(settings: Settings) -> LLMClient:
    openjarvis_url = os.environ.get("JARVIS_OPENJARVIS_API_URL", "").strip()
    if openjarvis_url:
        model = os.environ.get("JARVIS_OPENJARVIS_MODEL", "qwen3.5:4b").strip()
        return OpenJarvisClient(openjarvis_url, model or "qwen3.5:4b")
    if settings.llm_provider == "anthropic":
        key = (
            settings.anthropic_api_key.get_secret_value()
            if settings.anthropic_api_key is not None
            else ""
        )
        return AnthropicClient(key, settings.anthropic_model, allow_cloud=settings.allow_cloud)
    return OllamaClient(settings.ollama_url, settings.ollama_model, think=settings.ollama_think)


__all__ = ["AnthropicClient", "LLMClient", "LLMError", "OllamaClient", "OpenJarvisClient", "build_llm"]
