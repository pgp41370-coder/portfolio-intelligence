"""Provider-neutral market-data records.

Providers translate their own response formats into these types, so nothing outside
``app.market_data.providers`` depends on a particular vendor's JSON.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from app.portfolios.rules import Exchange

HistoricalPeriod = Literal["1m", "6m", "1yr"]


class UnpricedReason(StrEnum):
    LISTING_NOT_FOUND = "LISTING_NOT_FOUND"
    NO_NSE_LISTING = "NO_NSE_LISTING"
    NO_PRICE_DATA = "NO_PRICE_DATA"


@dataclass(frozen=True, slots=True)
class SecurityRecord:
    provider_security_id: str
    name: str
    nse_symbol: str | None
    bse_code: str | None
    isin: str | None = None


@dataclass(frozen=True, slots=True)
class SecurityMasterSnapshot:
    records: tuple[SecurityRecord, ...]
    dropped_rows: int = 0
    ambiguous_nse_symbols: tuple[str, ...] = ()
    ambiguous_bse_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DailyPriceBar:
    """One exchange trading day's reported closing price."""

    trade_date: date
    close_price: Decimal
    volume: int | None = None


@dataclass(frozen=True, slots=True)
class DailyPriceSeries:
    symbol: str
    exchange: Exchange
    bars: tuple[DailyPriceBar, ...]
    skipped_points: int = 0
