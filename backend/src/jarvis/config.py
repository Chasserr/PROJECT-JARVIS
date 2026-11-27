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
    # Vision is only advertised after a real image round-trip succeeds; see
    # jarvis.tools.vision.probe_vision.
    vision_model: str = "qwen3.5:4b"
    vision_timeout_s: float = Field(default=120.0, gt=0, le=600)
    # Runtime capability probes back the Connected/Partial labels on /agents.
    # Disabled in tests so the suite never depends on a live model or network.
    capability_probes: bool = True
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

    # --- Data connectors -------------------------------------------------
    # Empty means every configured source may be queried; a non-empty list
    # restricts queries to those ids. A source without its own credentials or
    # path still reports not_configured rather than pretending to work.
    connector_allowlist: list[str] = Field(default_factory=list)
    connector_timeout_s: float = Field(default=20.0, gt=0, le=120)
    connector_max_results: int = Field(default=8, ge=1, le=50)
    project_root: Path | None = None
    obsidian_vault: Path | None = None
    github_token: SecretStr | None = None
    github_api_url: str = "https://api.github.com"
    supabase_url: str | None = None
    supabase_key: SecretStr | None = None
    supabase_tables: list[str] = Field(default_factory=list)
    email_imap_host: str | None = None
    email_imap_port: int = Field(default=993, ge=1, le=65535)
    email_imap_ssl: bool = True
    email_smtp_host: str | None = None
    email_smtp_port: int = Field(default=465, ge=1, le=65535)
    email_smtp_ssl: bool = True
    email_smtp_starttls: bool = False
    email_user: str | None = None
    email_password: SecretStr | None = None
    email_from: str | None = None
    email_signature: str = ""

    # --- Execution sandbox -----------------------------------------------
    # shell.run is approval-gated and allowlisted, but an allowlisted
    # interpreter is still powerful; the approval prompt is the real control.
    shell_enabled: bool = True
    shell_allowed_commands: list[str] = Field(
        default_factory=lambda: [
            "python", "python3", "py", "pip-audit", "pytest",
            "node", "npm", "npx", "git", "ruff", "echo", "where",
        ]
    )
    shell_timeout_s: float = Field(default=60.0, gt=0, le=300)
    shell_max_output_chars: int = Field(default=20_000, ge=500, le=200_000)
    file_write_roots: list[Path] = Field(default_factory=list)
    browser_allowed_domains: list[str] = Field(default_factory=list)
    browser_timeout_ms: int = Field(default=20_000, ge=1_000, le=120_000)
    browser_max_chars: int = Field(default=20_000, ge=500, le=200_000)
    # pip-audit queries an advisory service, so this is longer than a normal command.
    scanner_timeout_s: float = Field(default=180.0, gt=0, le=600)
    reports_dir: Path | None = None

    # --- Telephony --------------------------------------------------------
    # Provider-independent voice gateway. Every call route stays closed until a
    # provider, its credentials, a public HTTPS base URL and at least one
    # authorised caller exist, because an open voice endpoint would be a
    # remote-control surface for this PC.
    telephony_provider: Literal["none", "twilio"] = "none"
    telephony_public_base_url: str | None = None
    telephony_allowed_callers: list[str] = Field(default_factory=list)
    telephony_greeting: str = "JARVIS here. What do you need?"
    telephony_voice: str = "Polly.Matthew"
    telephony_language: str = "en-US"
    telephony_speech_timeout_s: int = Field(default=3, ge=1, le=10)
    telephony_turn_timeout_s: float = Field(default=60.0, gt=0, le=180)
    telephony_poll_seconds: int = Field(default=3, ge=1, le=10)
    telephony_max_polls: int = Field(default=8, ge=1, le=20)
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str | None = None
    twilio_api_url: str = "https://api.twilio.com"

    @field_validator(
        "master_key",
        "anthropic_api_key",
        "api_token",
        "brave_api_key",
        "github_token",
        "supabase_key",
        "email_password",
        "twilio_auth_token",
        mode="before",
    )
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "database_path",
        "master_key_file",
        "skills_dir",
        "project_root",
        "obsidian_vault",
        "reports_dir",
        mode="before",
    )
    @classmethod
    def _blank_path_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "supabase_url",
        "telephony_public_base_url",
        "twilio_account_sid",
        "twilio_from_number",
        "email_imap_host",
        "email_smtp_host",
        "email_user",
        "email_from",
        mode="before",
    )
    @classmethod
    def _blank_str_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "file_search_roots",
        "file_write_roots",
        "connector_allowlist",
        "supabase_tables",
        "telephony_allowed_callers",
        "shell_allowed_commands",
        "browser_allowed_domains",
        mode="before",
    )
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
