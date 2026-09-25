"""ORM model for the transaction ledger.

Design decisions are recorded in docs/transactions.md. In short: quantities are always
positive and direction comes from ``kind``; costs are one total per transaction; and the
ledger is additive — a portfolio without transactions behaves exactly as it did in M4.1.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("fees >= 0", name="fees_not_negative"),
        CheckConstraint("kind IN ('BUY', 'SELL')", name="kind_valid"),
        CheckConstraint("exchange IN ('NSE', 'BSE')", name="exchange_valid"),
        CheckConstraint("symbol ~ '^[A-Z0-9][A-Z0-9&-]{0,19}$'", name="symbol_format"),
        Index("ix_transactions_portfolio_id_trade_date", "portfolio_id", "trade_date"),
        Index("ix_transactions_portfolio_id_symbol_exchange", "portfolio_id", "symbol", "exchange", "trade_date"),
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(20))
    exchange: Mapped[str] = mapped_column(String(3))
    kind: Mapped[str] = mapped_column(String(8))
    trade_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    # Brokerage, STT, stamp duty and GST combined: broker statements rarely separate them
    # cleanly, and splitting them here would invite fabricated detail.
    fees: Mapped[Decimal] = mapped_column(Numeric(14, 4), server_default=text("0"), default=Decimal(0))
    reference: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    portfolio: Mapped["object"] = relationship("Portfolio", back_populates="transactions")
