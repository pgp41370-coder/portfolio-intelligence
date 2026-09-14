"""Application settings, loaded from environment variables or a local .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Portfolio Intelligence API"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"

    # SecretStr keeps credentials out of logs, reprs and tracebacks.
    database_url: SecretStr | None = None

    # Parsed from a JSON list, e.g. CORS_ALLOWED_ORIGINS=["http://localhost:3000"]
    cors_allowed_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
