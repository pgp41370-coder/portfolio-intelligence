"""Valuation API response models.

Money and percentages are serialised as decimal strings with 2 decimal places
(ROUND_HALF_UP); prices as exact decimal strings. Missing values are null, never zero.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, PlainSerializer

from app.market_data.records import UnpricedReason
from app.portfolios.calculations import format_amount
from app.portfolios.rules import Exchange
from app.valuation.calculations import format_money, format_percent

Money = Annotated[Decimal, PlainSerializer(format_money, return_type=str)]
Percent = Annotated[Decimal, PlainSerializer(format_percent, return_type=str)]
Price = Annotated[Decimal, PlainSerializer(format_amount, return_type=str)]

METHODOLOGY_NOTE = (
    "Unrealized price return at the latest reported NSE end-of-day closing price. "
    "Not a live price. Excludes dividends, taxes and charges; not adjusted for corporate actions; "
    "not a total return. This is portfolio analytics, not personalized investment advice."
)


class ValuationStatus(StrEnum):
    VALUED = "VALUED"
    STALE = "STALE"
    UNPRICED = "UNPRICED"


class HoldingWarning(StrEnum):
    LARGE_PRICE_MOVE = "LARGE_PRICE_MOVE"


class PriceRead(BaseModel):
    close_price: Price
    trade_date: date
    exchange: Exchange
    source: str
    source_name: str
    fetched_at: datetime


class HoldingValuationRead(BaseModel):
    holding_id: uuid.UUID
    symbol: str
    exchange: Exchange
    quantity: int
    average_buy_price: Price
    status: ValuationStatus
    unpriced_reason: UnpricedReason | None
    price: PriceRead | None
    invested_value: Money
    market_value: Money | None
    unrealized_pnl: Money | None
    unrealized_return_pct: Percent | None
    weight_pct: Percent | None
    warnings: list[HoldingWarning]


class ValuationTotalsRead(BaseModel):
    total_invested_value: Money
    priced_invested_value: Money
    total_market_value: Money | None
    total_unrealized_pnl: Money | None
    total_unrealized_return_pct: Percent | None
    is_complete: bool


class FreshnessSummaryRead(BaseModel):
    expected_session_date: date
    latest_price_date: date | None
    oldest_price_date: date | None
    valued_count: int
    stale_count: int
    unpriced_count: int


class MethodologyRead(BaseModel):
    price_basis: Literal["NSE_EOD_CLOSE"] = "NSE_EOD_CLOSE"
    currency: Literal["INR"] = "INR"
    rounding: str = "Money and percentages to 2 decimal places, ROUND_HALF_UP"
    note: str = METHODOLOGY_NOTE


class PortfolioValuationRead(BaseModel):
    portfolio_id: uuid.UUID
    portfolio_name: str
    valued_at: datetime
    market_data_configured: bool
    methodology: MethodologyRead
    freshness: FreshnessSummaryRead
    totals: ValuationTotalsRead
    holdings: list[HoldingValuationRead]
