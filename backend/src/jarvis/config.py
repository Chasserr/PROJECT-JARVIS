"""Typed configuration. Every setting is overridable through ``JARVIS_*`` env vars."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "JARVIS"
    environment: Literal["dev", "test", "prod"] = "dev"
    data_dir: Path = Path("data")
    database_path: Path | None = None
    master_key: SecretStr | None = None
    master_key_file: Path | None = None

    llm_provider: Literal["ollama", "anthropic"] = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:2b"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_think: bool = False
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-4-5"
    allow_cloud: bool = False

    max_plan_steps: int = Field(default=12, ge=1, le=50)
    max_replans: int = Field(default=2, ge=0, le=5)
    tool_timeout_s: float = Field(default=30.0, gt=0, le=300)
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8766, ge=1, le=65535)
    api_token: SecretStr | None = None
    cors_origins: list[str] = Field(default_factory=list)
    rate_limit_per_minute: int = Field(default=120, ge=0, le=10_000)
    log_level: str = "INFO"
    tool_permissions: dict[str, str] = Field(default_factory=dict)

    skills_dir: Path | None = None
    brave_api_key: SecretStr | None = None
    web_search_results: int = Field(default=5, ge=1, le=10)
    web_read_max_bytes: int = Field(default=1_000_000, ge=1_000, le=20_000_000)
    web_read_max_chars: int = Field(default=20_000, ge=500, le=200_000)
    web_read_timeout_s: float = Field(default=15.0, gt=0, le=120)
    file_search_roots: list[Path] = Field(default_factory=list)
    file_search_max_results: int = Field(default=20, ge=1, le=200)
    file_search_max_entries: int = Field(default=20_000, ge=100, le=500_000)

    @field_validator("master_key", "anthropic_api_key", "api_token", "brave_api_key", mode="before")
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_path", "master_key_file", "skills_dir", mode="before")
    @classmethod
    def _blank_path_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("file_search_roots", mode="before")
    @classmethod
    def _parse_roots(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("tool_permissions", mode="before")
    @classmethod
    def _parse_tool_permissions(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return {}
            return json.loads(value)
        return value

    @property
    def db_path(self) -> Path:
        return self.database_path or self.data_dir / "jarvis.sqlite3"

    @property
    def key_path(self) -> Path:
        return self.master_key_file or self.data_dir / "master.key"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
