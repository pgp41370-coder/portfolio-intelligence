"""Application settings, loaded from environment variables or a local .env file."""

from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.market_data.calendar import TradingCalendar
from app.market_data.nse_calendar import (
    CALENDAR_COMPLETE_FROM,
    CALENDAR_COMPLETE_TO,
    NSE_SPECIAL_TRADING_SESSIONS,
    NSE_TRADING_HOLIDAYS,
)

DEVELOPMENT_CORS_ORIGINS = ("http://localhost:3000",)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


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
    # "session": a direct or session-pooler connection (local PostgreSQL, migrations, market-data
    # sync). "transaction": a transaction-mode pooler such as Supabase's port 6543, for the
    # serverless API. Prepared statements and client-side pooling are then disabled, and
    # session features such as advisory locks are unavailable.
    database_pool_mode: Literal["session", "transaction"] = "session"

    # Browser origins allowed to call the API directly, as a JSON list, e.g.
    # CORS_ALLOWED_ORIGINS=["https://portfolio-intelligence-bice.vercel.app"]. When unset:
    # localhost in development and test, none in production. Production origins must be
    # explicit https:// origins.
    cors_allowed_origins: list[str] | None = None

    # Write endpoints (create portfolios, add or delete holdings, CSV preview and import). When
    # unset they are enabled everywhere except production, where the public demo is read-only.
    enable_write_api: bool | None = None

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
    # NSE trading calendar for the price-freshness rules, as JSON lists of ISO dates. The
    # defaults are the published NSE calendar in app/market_data/nse_calendar.py; setting a
    # variable replaces its list.
    nse_trading_holidays: list[date] = Field(default_factory=lambda: sorted(NSE_TRADING_HOLIDAYS))
    # Exchange-declared sessions on days that are normally closed (e.g. a Sunday Budget session).
    nse_special_trading_sessions: list[date] = Field(default_factory=lambda: sorted(NSE_SPECIAL_TRADING_SESSIONS))
    # Annual risk-free rate as a percentage, e.g. 6.5 for 6.5%. Unset by default: without a
    # real rate the Sharpe ratio is withheld rather than computed against an assumed one.
    risk_free_rate_pct: Decimal | None = None

    # The range the holiday lists are known to be complete for. Outside it the application says
    # so rather than treating every weekday as a confirmed trading session.
    nse_calendar_complete_from: date | None = CALENDAR_COMPLETE_FROM
    nse_calendar_complete_to: date | None = CALENDAR_COMPLETE_TO

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

    @model_validator(mode="after")
    def _cors_origins_for_environment(self) -> "Settings":
        if self.cors_allowed_origins is None:
            self.cors_allowed_origins = [] if self.app_env == "production" else list(DEVELOPMENT_CORS_ORIGINS)
        elif self.app_env == "production":
            for origin in self.cors_allowed_origins:
                parts = urlsplit(origin)
                if (
                    parts.scheme != "https"
                    or not parts.hostname
                    or parts.hostname in _LOCAL_HOSTS
                    or parts.path
                    or parts.query
                    or "*" in origin
                ):
                    raise ValueError(
                        f"Production CORS origins must be explicit https:// origins without a path; {origin!r} is not allowed."
                    )
        return self

    @model_validator(mode="after")
    def _calendar_dates_do_not_overlap(self) -> "Settings":
        overlap = set(self.nse_trading_holidays) & set(self.nse_special_trading_sessions)
        if overlap:
            raise ValueError(
                f"NSE_TRADING_HOLIDAYS and NSE_SPECIAL_TRADING_SESSIONS share dates: {sorted(overlap)}"
            )
        return self

    @property
    def risk_free_rate(self) -> Decimal | None:
        """The configured annual risk-free rate as a fraction, or None if unset."""
        return self.risk_free_rate_pct / Decimal(100) if self.risk_free_rate_pct is not None else None

    @property
    def market_data_configured(self) -> bool:
        return self.indian_api_key is not None

    @property
    def write_api_enabled(self) -> bool:
        if self.enable_write_api is not None:
            return self.enable_write_api
        return self.app_env != "production"

    @property
    def api_docs_enabled(self) -> bool:
        return self.app_env != "production"

    @property
    def trading_calendar(self) -> TradingCalendar:
        return TradingCalendar(
            holidays=frozenset(self.nse_trading_holidays),
            special_sessions=frozenset(self.nse_special_trading_sessions),
            complete_from=self.nse_calendar_complete_from,
            complete_to=self.nse_calendar_complete_to,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
