"""Shared fixtures and a scripted LLM for deterministic tests."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from jarvis.config import Settings
from jarvis.container import Container, build_container
from jarvis.llm.base import LLMError, LLMResponse, Message


class FakeLLM:
    model = "fake-model"

    def __init__(self, responses: list[str | LLMResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[list[Message]] = []

    async def complete(self, messages, **kwargs) -> LLMResponse:
        self.calls.append(list(messages))
        if not self.responses:
            raise LLMError("fake LLM ran out of responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, LLMResponse):
            return response
        return LLMResponse(text=response, model=self.model)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        data_dir=tmp_path,
        database_path=tmp_path / "jarvis-test.sqlite3",
        master_key=base64.b64encode(b"k" * 32).decode(),
        api_token=None,
        brave_api_key=None,
        ollama_embed_model="",
        max_replans=1,
        capability_probes=False,
    )


@pytest.fixture
def db(settings: Settings):
    from jarvis.db import Database

    database = Database(settings.db_path)
    database.initialize()
    return database


@pytest.fixture
def box(settings: Settings):
    from jarvis.security.crypto import SecretBox

    return SecretBox.from_settings(settings)


@pytest.fixture
def container(settings: Settings) -> Container:
    return build_container(settings, llm=FakeLLM([]), embeddings=None)
