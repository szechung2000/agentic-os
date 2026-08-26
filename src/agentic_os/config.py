"""Configuration (AGOS_ prefix)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGOS_", env_file=".env", extra="ignore")

    # agent-memory service the OS is built on
    memory_url: str = "http://localhost:8000"
    openai_api_key: str | None = None
    telegram_bot_token: str | None = None
    # which model drives the supervisor (only used with a key)
    supervisor_model: str = "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
