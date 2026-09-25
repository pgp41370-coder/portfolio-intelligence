"""Database access for market-data tables."""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import and_, distinct, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.market_data.models import DailyPrice, Listing, MarketDataSyncRun
from app.market_data.records import DailyPriceBar, SecurityRecord
from app.portfolios.models import Holding
from app.portfolios.rules import Exchange

_CHUNK_SIZE = 1000


@dataclass(frozen=True, slots=True)
class UpsertCounts:
    inserted: int
    updated: int
    unchanged: int


# --- Listings --------------------------------------------------------------------------


def count_active_listings(session: Session, provider: str) -> int:
    statement = select(func.count()).select_from(Listing).where(Listing.provider == provider, Listing.is_active.is_(True))
    return int(session.scalar(statement) or 0)


def replace_security_master(
    session: Session,
    provider: str,
    records: Sequence[SecurityRecord],
    *,
    seen_at: datetime,
) -> tuple[UpsertCounts, int]:
    """Upsert the provider's security list within the caller's transaction.

    Exchange codes are reassigned from scratch, so a symbol that moved to another security
    can never keep mapping to the old one. Securities missing from the list are marked
    inactive and keep no codes. Returns (counts, deactivated).
    """
    session.execute(update(Listing).where(Listing.provider == provider).values(nse_symbol=None, bse_code=None))

    inserted = updated = 0
    for start in range(0, len(records), _CHUNK_SIZE):
        chunk = records[start : start + _CHUNK_SIZE]
        statement = insert(Listing).values(
            [
                {
                    "provider": provider,
                    "provider_security_id": record.provider_security_id,
                    "name": record.name,
                    "nse_symbol": record.nse_symbol,
                    "bse_code": record.bse_code,
                    "isin": record.isin,
                    "is_active": True,
                    "last_seen_at": seen_at,
                }
                for record in chunk
            ]
        )
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[Listing.provider, Listing.provider_security_id],
            set_={
                "name": excluded.name,
                "nse_symbol": excluded.nse_symbol,
                "bse_code": excluded.bse_code,
                "isin": func.coalesce(excluded.isin, Listing.isin),
                "is_active": True,
                "last_seen_at": excluded.last_seen_at,
                "updated_at": func.now(),
            },
        ).returning(literal_column("(xmax = 0)"))
        flags = session.execute(statement).scalars().all()
        inserted += sum(1 for flag in flags if flag)
        updated += sum(1 for flag in flags if not flag)

    deactivated = session.execute(
        update(Listing)
        .where(Listing.provider == provider, Listing.last_seen_at < seen_at, Listing.is_active.is_(True))
        .values(is_active=False)
    ).rowcount
    return UpsertCounts(inserted=inserted, updated=updated, unchanged=0), int(deactivated or 0)


def listings_by_codes(
    session: Session,
    provider: str,
    nse_symbols: Collection[str],
    bse_codes: Collection[str],
) -> tuple[dict[str, Listing], dict[str, Listing]]:
    by_nse: dict[str, Listing] = {}
    by_bse: dict[str, Listing] = {}
    active = and_(Listing.provider == provider, Listing.is_active.is_(True))
    if nse_symbols:
        for listing in session.scalars(select(Listing).where(active, Listing.nse_symbol.in_(sorted(nse_symbols)))):
            by_nse[listing.nse_symbol or ""] = listing
    if bse_codes:
        for listing in session.scalars(select(Listing).where(active, Listing.bse_code.in_(sorted(bse_codes)))):
            by_bse[listing.bse_code or ""] = listing
    return by_nse, by_bse


def mark_price_request(session: Session, listing_id: uuid.UUID, *, requested_at: datetime, status: str) -> None:
    session.execute(
        update(Listing)
        .where(Listing.id == listing_id)
        .values(prices_last_requested_at=requested_at, prices_last_request_status=status)
    )


# --- Holdings --------------------------------------------------------------------------


def held_security_keys(session: Session, portfolio_id: uuid.UUID | None = None) -> list[tuple[Exchange, str]]:
    statement = select(Holding.exchange, Holding.symbol).distinct()
    if portfolio_id is not None:
        statement = statement.where(Holding.portfolio_id == portfolio_id)
    rows = session.execute(statement.order_by(Holding.exchange, Holding.symbol))
    return [(Exchange(exchange), symbol) for exchange, symbol in rows]


# --- Prices ----------------------------------------------------------------------------


def latest_trade_dates(session: Session, listing_ids: Collection[uuid.UUID], exchange: Exchange) -> dict[uuid.UUID, date]:
    if not listing_ids:
        return {}
    statement = (
        select(DailyPrice.listing_id, func.max(DailyPrice.trade_date))
        .where(DailyPrice.listing_id.in_(list(listing_ids)), DailyPrice.exchange == exchange.value)
        .group_by(DailyPrice.listing_id)
    )
    return {listing_id: latest for listing_id, latest in session.execute(statement)}


def recent_prices(
    session: Session,
    listing_ids: Collection[uuid.UUID],
    exchange: Exchange,
    *,
    per_listing: int = 2,
) -> dict[uuid.UUID, list[DailyPrice]]:
    """The most recent prices per listing, newest first."""
    if not listing_ids:
        return {}
    ranked = (
        select(
            DailyPrice,
            func.row_number()
            .over(partition_by=DailyPrice.listing_id, order_by=DailyPrice.trade_date.desc())
            .label("position"),
        )
        .where(DailyPrice.listing_id.in_(list(listing_ids)), DailyPrice.exchange == exchange.value)
        .subquery()
    )
    price = aliased(DailyPrice, ranked)
    statement = (
        select(price)
        .where(ranked.c.position <= per_listing)
        .order_by(ranked.c.listing_id, ranked.c.trade_date.desc())
    )
    result: dict[uuid.UUID, list[DailyPrice]] = {}
    for row in session.scalars(statement):
        result.setdefault(row.listing_id, []).append(row)
    return result


def upsert_daily_prices(
    session: Session,
    *,
    listing_id: uuid.UUID,
    exchange: Exchange,
    bars: Sequence[DailyPriceBar],
    source: str,
    fetched_at: datetime,
    sync_run_id: uuid.UUID | None,
) -> UpsertCounts:
    """Insert new daily prices and update revised ones; identical re-deliveries change nothing."""
    if not bars:
        return UpsertCounts(0, 0, 0)
    rows = [
        {
            "listing_id": listing_id,
            "exchange": exchange.value,
            "trade_date": bar.trade_date,
            "close_price": bar.close_price,
            "volume": bar.volume,
            "source": source,
            "fetched_at": fetched_at,
            "sync_run_id": sync_run_id,
        }
        for bar in bars
    ]
    statement = insert(DailyPrice).values(rows)
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        index_elements=[DailyPrice.listing_id, DailyPrice.exchange, DailyPrice.trade_date],
        set_={
            "close_price": excluded.close_price,
            "volume": func.coalesce(excluded.volume, DailyPrice.volume),
            "source": excluded.source,
            "fetched_at": excluded.fetched_at,
            "sync_run_id": excluded.sync_run_id,
        },
        where=or_(
            DailyPrice.close_price.is_distinct_from(excluded.close_price),
            and_(excluded.volume.is_not(None), DailyPrice.volume.is_distinct_from(excluded.volume)),
        ),
    ).returning(literal_column("(xmax = 0)"))
    flags = session.execute(statement).scalars().all()
    inserted = sum(1 for flag in flags if flag)
    return UpsertCounts(inserted=inserted, updated=len(flags) - inserted, unchanged=len(rows) - len(flags))


def price_series(
    session: Session,
    listing_ids: Collection[uuid.UUID],
    exchange: Exchange,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[uuid.UUID, list[DailyPrice]]:
    """Every stored close per listing within an inclusive date range, oldest first."""
    if not listing_ids:
        return {}
    statement = select(DailyPrice).where(
        DailyPrice.listing_id.in_(list(listing_ids)), DailyPrice.exchange == exchange.value
    )
    if start is not None:
        statement = statement.where(DailyPrice.trade_date >= start)
    if end is not None:
        statement = statement.where(DailyPrice.trade_date <= end)
    series: dict[uuid.UUID, list[DailyPrice]] = {}
    for row in session.scalars(statement.order_by(DailyPrice.listing_id, DailyPrice.trade_date)):
        series.setdefault(row.listing_id, []).append(row)
    return series


def count_listings_with_prices(session: Session, provider: str, exchange: Exchange) -> int:
    statement = (
        select(func.count(distinct(DailyPrice.listing_id)))
        .join(Listing, Listing.id == DailyPrice.listing_id)
        .where(Listing.provider == provider, DailyPrice.exchange == exchange.value)
    )
    return int(session.scalar(statement) or 0)


def latest_trade_date(session: Session, provider: str, exchange: Exchange) -> date | None:
    statement = (
        select(func.max(DailyPrice.trade_date))
        .join(Listing, Listing.id == DailyPrice.listing_id)
        .where(Listing.provider == provider, DailyPrice.exchange == exchange.value)
    )
    return session.scalar(statement)


# --- Sync runs -------------------------------------------------------------------------


def requests_used_since(session: Session, provider: str, since: datetime) -> int:
    statement = select(func.coalesce(func.sum(MarketDataSyncRun.requests_made), 0)).where(
        MarketDataSyncRun.provider == provider, MarketDataSyncRun.started_at >= since
    )
    return int(session.scalar(statement) or 0)


def latest_sync_run(
    session: Session,
    provider: str,
    kind: str,
    *,
    statuses: Collection[str] | None = None,
) -> MarketDataSyncRun | None:
    statement = select(MarketDataSyncRun).where(MarketDataSyncRun.provider == provider, MarketDataSyncRun.kind == kind)
    if statuses:
        statement = statement.where(MarketDataSyncRun.status.in_(list(statuses)))
    return session.scalars(statement.order_by(MarketDataSyncRun.started_at.desc()).limit(1)).first()
