"""The interface every market-data provider implements.

Sync code depends only on this protocol and the records in ``app.market_data.records``.
Replacing Indian API means writing another class with these methods.
"""

from collections.abc import Callable
from typing import Protocol

from app.market_data.records import DailyPriceSeries, HistoricalPeriod, SecurityMasterSnapshot


class MarketDataProvider(Protocol):
    @property
    def name(self) -> str:
        """Stable key stored with every record, e.g. ``indian_api``."""
        ...

    @property
    def display_name(self) -> str:
        """Name shown to users, e.g. ``Indian API``."""
        ...

    def set_request_guard(self, guard: Callable[[], None] | None) -> None:
        """Register a callable run before every metered request; it raises to block the request."""
        ...

    def get_security_master(self) -> SecurityMasterSnapshot:
        """Return the provider's list of securities with their exchange codes."""
        ...

    def get_daily_prices(self, nse_symbol: str, period: HistoricalPeriod) -> DailyPriceSeries:
        """Return validated, dated NSE end-of-day closing prices for one security."""
        ...

    def close(self) -> None: ...
