"""Read-side market-data services: price lookups for valuation and operational status.

These functions read the database only; they never call a provider.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.market_data import repository
from app.market_data.calendar import PriceFreshness, classify_freshness, ist_month_start, latest_expected_session
from app.market_data.models import DailyPrice
from app.market_data.providers import provider_display_name
from app.market_data.records import UnpricedReason
from app.market_data.schemas import HeldSecurityFreshnessRead, MarketDataStatusRead, SyncRunRead
from app.portfolios.rules import Exchange

SecurityKey = tuple[Exchange, str]


@dataclass(frozen=True, slots=True)
class PricePoint:
    close_price: Decimal
    trade_date: date
    exchange: Exchange
    source: str
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class PriceLookup:
    listing_id: uuid.UUID | None
    unpriced_reason: UnpricedReason | None
    latest: PricePoint | None
    previous: PricePoint | None


def lookup_latest_prices(session: Session, provider: str, keys: Iterable[SecurityKey]) -> dict[SecurityKey, PriceLookup]:
    """Resolve (exchange, symbol) holdings to the latest stored NSE end-of-day price.

    NSE holdings match on NSE symbol. BSE holdings match on BSE scrip code and use the NSE
    closing price of the same security when one exists; M3A stores NSE prices only.
    """
    unique_keys = set(keys)
    nse_symbols = {code for exchange, code in unique_keys if exchange is Exchange.NSE}
    bse_codes = {code for exchange, code in unique_keys if exchange is Exchange.BSE}
    by_nse, by_bse = repository.listings_by_codes(session, provider, nse_symbols, bse_codes)

    resolved: dict[SecurityKey, tuple[uuid.UUID | None, UnpricedReason | None]] = {}
    priceable: set[uuid.UUID] = set()
    for key in unique_keys:
        exchange, code = key
        listing = by_nse.get(code) if exchange is Exchange.NSE else by_bse.get(code)
        if listing is None:
            resolved[key] = (None, UnpricedReason.LISTING_NOT_FOUND)
        elif listing.nse_symbol is None:
            resolved[key] = (listing.id, UnpricedReason.NO_NSE_LISTING)
        else:
            resolved[key] = (listing.id, None)
            priceable.add(listing.id)

    prices = repository.recent_prices(session, priceable, Exchange.NSE, per_listing=2)
    lookups: dict[SecurityKey, PriceLookup] = {}
    for key, (listing_id, reason) in resolved.items():
        rows = prices.get(listing_id, []) if listing_id is not None and reason is None else []
        if reason is None and not rows:
            reason = UnpricedReason.NO_PRICE_DATA
        lookups[key] = PriceLookup(
            listing_id=listing_id,
            unpriced_reason=reason,
            latest=_point(rows[0]) if rows else None,
            previous=_point(rows[1]) if len(rows) > 1 else None,
        )
    return lookups


def get_status(session: Session, settings: Settings, now: datetime) -> MarketDataStatusRead:
    provider = settings.market_data_provider
    expected = latest_expected_session(now, frozenset(settings.nse_trading_holidays))

    counts = {PriceFreshness.FRESH: 0, PriceFreshness.STALE: 0}
    unpriced = 0
    for lookup in lookup_latest_prices(session, provider, repository.held_security_keys(session)).values():
        if lookup.latest is None:
            unpriced += 1
        else:
            counts[classify_freshness(lookup.latest.trade_date, expected)] += 1

    last_listing = repository.latest_sync_run(session, provider, "security_master")
    last_price = repository.latest_sync_run(session, provider, "daily_prices")
    last_success = repository.latest_sync_run(session, provider, "daily_prices", statuses=("succeeded",))

    return MarketDataStatusRead(
        provider=provider,
        provider_name=provider_display_name(provider),
        configured=settings.market_data_configured,
        monthly_request_budget=settings.market_data_monthly_request_budget,
        requests_used_this_month=repository.requests_used_since(session, provider, ist_month_start(now)),
        active_listings=repository.count_active_listings(session, provider),
        securities_with_prices=repository.count_listings_with_prices(session, provider, Exchange.NSE),
        latest_trade_date=repository.latest_trade_date(session, provider, Exchange.NSE),
        expected_session_date=expected,
        last_listing_sync=SyncRunRead.model_validate(last_listing) if last_listing else None,
        last_price_sync=SyncRunRead.model_validate(last_price) if last_price else None,
        last_successful_price_sync_at=last_success.completed_at if last_success else None,
        held_securities=HeldSecurityFreshnessRead(
            valued=counts[PriceFreshness.FRESH],
            stale=counts[PriceFreshness.STALE],
            unpriced=unpriced,
        ),
    )


def _point(row: DailyPrice) -> PricePoint:
    return PricePoint(
        close_price=row.close_price,
        trade_date=row.trade_date,
        exchange=Exchange(row.exchange),
        source=row.source,
        fetched_at=row.fetched_at,
    )
