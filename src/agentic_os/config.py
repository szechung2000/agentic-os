"""Configuration (AGOS_ prefix)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGOS_", env_file=".env", extra="ignore")

    # agent-memory service the OS is built on
    memory_url: str = "http://localhost:8000"
    # Deliberately local-only defaults. Multi-user deployments must provide
    # stable AGOS_MEMORY_* identifiers at their authenticated entry point.
    memory_user_id: str = Field(default="local-user", pattern=_IDENTIFIER_PATTERN)
    memory_project_id: str = Field(default="default-project", pattern=_IDENTIFIER_PATTERN)
    memory_run_id: str = Field(default="interactive-run", pattern=_IDENTIFIER_PATTERN)
    memory_task_id: str = Field(default="interactive-task", pattern=_IDENTIFIER_PATTERN)
    memory_worker_id: str = Field(default="memory-worker", pattern=_IDENTIFIER_PATTERN)
    openai_api_key: str | None = None
    telegram_bot_token: str | None = None
    # which model drives the supervisor (only used with a key)
    supervisor_model: str = "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
