"""Application settings, loaded from environment variables or a local .env file."""

from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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

    # --- Market data -----------------------------------------------------------------
    # The provider key is backend-only: it is never returned by the API, logged or sent
    # to the browser. Without it the app still runs and valuations report missing prices.
    market_data_provider: Literal["indian_api"] = "indian_api"
    indian_api_key: SecretStr | None = None
    indian_api_base_url: str = "https://stock.indianapi.in"
    indian_api_security_master_url: str = "https://analyst.indianapi.in/static/all_stocks.json"
    # Conservative internal cap below the provider's free tier of 500 requests per month.
    market_data_monthly_request_budget: int = Field(default=450, ge=1, le=500)
    market_data_min_request_interval_seconds: float = Field(default=1.1, ge=1.1)
    market_data_request_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    market_data_backfill_period: Literal["1m", "6m", "1yr"] = "1yr"
    # Exchange holidays (JSON list of ISO dates) used by the price-freshness rule.
    nse_trading_holidays: list[date] = []

    @field_validator("database_url", "indian_api_key", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("indian_api_base_url", "indian_api_security_master_url")
    @classmethod
    def _require_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("Market-data provider URLs must use https://")
        return value.rstrip("/")

    @property
    def market_data_configured(self) -> bool:
        return self.indian_api_key is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()
