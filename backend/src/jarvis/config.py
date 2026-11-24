from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JARVIS_", env_file=".env", extra="ignore")

    app_name: str = "JARVIS"
    environment: str = "development"
    database_path: str = "../data/jarvis-core.sqlite3"
    provider: str = "claude"
    cloud_enabled: bool = False
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5"
    local_base_url: str = "http://127.0.0.1:1234/v1"
    local_api_key: str = "lm-studio"
    local_model: str = "google/gemma-4-e2b"
    max_agent_steps: int = 8
    max_retries_per_step: int = 0  # Tool actions are never retried automatically.
    planner_timeout_seconds: float = 75.0
    tool_timeout_seconds: float = 90.0
    critic_timeout_seconds: float = 45.0
    max_concurrent_tools: int = 2
    skill_manifest_path: str = "config/skills.json"
    kill_switch: bool = False


settings = Settings()
