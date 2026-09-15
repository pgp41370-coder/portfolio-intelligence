"""ORM models for market data.

Only provider-reported facts are stored: securities and their exchange codes, dated
closing prices, and a record of every sync. Market value, P&L, returns and weights are
always calculated, never stored.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SYNC_KINDS = ("security_master", "daily_prices")
SYNC_STATUSES = ("running", "succeeded", "partial", "failed", "rate_limited", "budget_exhausted")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class Listing(Base):
    """A security in the provider's security master, with its NSE and BSE codes."""

    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("provider", "provider_security_id"),
        UniqueConstraint("provider", "nse_symbol"),
        UniqueConstraint("provider", "bse_code"),
        CheckConstraint("nse_symbol ~ '^[A-Z0-9][A-Z0-9&-]{0,19}$'", name="nse_symbol_format"),
        CheckConstraint("bse_code ~ '^[0-9]{6}$'", name="bse_code_format"),
        CheckConstraint("isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'", name="isin_format"),
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    provider: Mapped[str] = mapped_column(String(32))
    provider_security_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    nse_symbol: Mapped[str | None] = mapped_column(String(20))
    bse_code: Mapped[str | None] = mapped_column(String(6))
    isin: Mapped[str | None] = mapped_column(String(12))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prices_last_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prices_last_request_status: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MarketDataSyncRun(Base):
    """One execution of a sync, kept for operational transparency and request accounting."""

    __tablename__ = "market_data_sync_runs"
    __table_args__ = (
        CheckConstraint(_in_list("kind", SYNC_KINDS), name="kind_valid"),
        CheckConstraint(_in_list("status", SYNC_STATUSES), name="status_valid"),
        CheckConstraint(
            "requests_made >= 0 AND records_attempted >= 0 AND records_inserted >= 0 "
            "AND records_updated >= 0 AND failures >= 0",
            name="counters_non_negative",
        ),
        Index("ix_market_data_sync_runs_provider_kind_started_at", "provider", "kind", "started_at"),
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    provider: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requests_made: Mapped[int] = mapped_column(Integer, server_default="0")
    records_attempted: Mapped[int] = mapped_column(Integer, server_default="0")
    records_inserted: Mapped[int] = mapped_column(Integer, server_default="0")
    records_updated: Mapped[int] = mapped_column(Integer, server_default="0")
    failures: Mapped[int] = mapped_column(Integer, server_default="0")
    error_summary: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class DailyPrice(Base):
    """A reported end-of-day closing price for one security on one exchange trading date."""

    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint("listing_id", "exchange", "trade_date"),
        CheckConstraint("exchange IN ('NSE', 'BSE')", name="exchange_valid"),
        CheckConstraint("close_price > 0", name="close_price_positive"),
        CheckConstraint("volume IS NULL OR volume >= 0", name="volume_non_negative"),
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    exchange: Mapped[str] = mapped_column(String(3))
    trade_date: Mapped[date] = mapped_column(Date)
    close_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("market_data_sync_runs.id", ondelete="SET NULL")
    )
