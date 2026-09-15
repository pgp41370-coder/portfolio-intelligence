"""API response models for market-data status. Never includes credentials."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    requests_made: int
    records_attempted: int
    records_inserted: int
    records_updated: int
    failures: int
    error_summary: str | None


class HeldSecurityFreshnessRead(BaseModel):
    """Distinct securities held across all portfolios, by price status."""

    valued: int
    stale: int
    unpriced: int


class MarketDataStatusRead(BaseModel):
    provider: str
    provider_name: str
    configured: bool
    price_basis: Literal["NSE_EOD_CLOSE"] = "NSE_EOD_CLOSE"
    monthly_request_budget: int
    requests_used_this_month: int
    active_listings: int
    securities_with_prices: int
    latest_trade_date: date | None
    expected_session_date: date
    last_listing_sync: SyncRunRead | None
    last_price_sync: SyncRunRead | None
    last_successful_price_sync_at: datetime | None
    held_securities: HeldSecurityFreshnessRead
