"""Market-data providers and the factory that selects one from settings."""

from app.core.config import Settings
from app.market_data.providers.base import MarketDataProvider

PROVIDER_DISPLAY_NAMES = {"indian_api": "Indian API"}


def provider_display_name(provider_key: str) -> str:
    return PROVIDER_DISPLAY_NAMES.get(provider_key, provider_key)


def build_provider(settings: Settings) -> MarketDataProvider:
    if settings.market_data_provider == "indian_api":
        from app.market_data.providers.indian_api import IndianApiProvider

        return IndianApiProvider.from_settings(settings)
    raise ValueError(f"Unsupported market-data provider: {settings.market_data_provider}")
