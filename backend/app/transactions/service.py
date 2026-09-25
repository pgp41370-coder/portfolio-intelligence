"""Transaction service: every read and write of the ledger goes through here.

Two rules need context the input schema does not have, so they live here: a trade cannot be
dated after the latest completed session, and no day's closing position may go negative. Both
reject the input rather than adjusting it.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.performance.positions import LedgerEvent, OversoldLedgerError, validate_ledger
from app.portfolios.service import PortfolioNotFoundError, get_portfolio
from app.transactions.models import Transaction
from app.transactions.rules import MAX_TRANSACTIONS_PER_PORTFOLIO
from app.transactions.schemas import TransactionInput


class TransactionNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(404, "transaction_not_found", "Transaction not found in this portfolio.")


class TransactionLimitError(AppError):
    def __init__(self) -> None:
        super().__init__(
            422,
            "transaction_limit_reached",
            f"A portfolio can have at most {MAX_TRANSACTIONS_PER_PORTFOLIO:,} transactions.",
        )


class FutureTradeDateError(AppError):
    def __init__(self, trade_date: date, latest_session: date) -> None:
        super().__init__(
            422,
            "future_trade_date",
            f"Trade date {trade_date:%d %b %Y} is after the latest completed NSE session "
            f"({latest_session:%d %b %Y}).",
        )


class OversoldError(AppError):
    def __init__(self, error: OversoldLedgerError) -> None:
        super().__init__(422, "oversold_position", str(error))


def list_transactions(session: Session, portfolio_id: uuid.UUID) -> list[Transaction]:
    """The whole ledger in deterministic order: trade date, then insertion order."""
    get_portfolio(session, portfolio_id)  # 404 rather than an empty list for an unknown portfolio
    return list(
        session.scalars(
            select(Transaction)
            .where(Transaction.portfolio_id == portfolio_id)
            .order_by(Transaction.trade_date, Transaction.created_at, Transaction.id)
        )
    )


def add_transactions(
    session: Session,
    portfolio_id: uuid.UUID,
    items: list[TransactionInput],
    *,
    latest_session: date,
) -> list[Transaction]:
    """Append transactions, validating the resulting ledger as a whole before committing."""
    portfolio = get_portfolio(session, portfolio_id)
    if portfolio is None:  # pragma: no cover - get_portfolio raises
        raise PortfolioNotFoundError()

    existing = list_transactions(session, portfolio_id)
    if len(existing) + len(items) > MAX_TRANSACTIONS_PER_PORTFOLIO:
        raise TransactionLimitError()

    for item in items:
        if item.trade_date > latest_session:
            raise FutureTradeDateError(item.trade_date, latest_session)

    # Validate the ledger it would become, not just the new rows: a sell is only valid in the
    # context of everything already recorded.
    prospective = [_event(row) for row in existing] + [
        LedgerEvent(
            trade_date=item.trade_date,
            symbol=item.symbol,
            exchange=item.exchange.value,
            kind=item.kind,
            quantity=item.quantity,
            price=item.price,
            fees=item.fees,
        )
        for item in items
    ]
    try:
        validate_ledger(prospective)
    except OversoldLedgerError as error:
        raise OversoldError(error) from None

    created = [
        Transaction(
            portfolio_id=portfolio_id,
            symbol=item.symbol,
            exchange=item.exchange.value,
            kind=item.kind,
            trade_date=item.trade_date,
            quantity=item.quantity,
            price=item.price,
            fees=item.fees,
            reference=item.reference,
        )
        for item in items
    ]
    session.add_all(created)
    session.commit()
    for row in created:
        session.refresh(row)
    return created


def delete_transaction(session: Session, portfolio_id: uuid.UUID, transaction_id: uuid.UUID) -> None:
    """Remove one transaction, refusing if the remaining ledger would be oversold."""
    get_portfolio(session, portfolio_id)
    row = session.scalars(
        select(Transaction).where(
            Transaction.portfolio_id == portfolio_id, Transaction.id == transaction_id
        )
    ).first()
    if row is None:
        raise TransactionNotFoundError()

    remaining = [_event(other) for other in list_transactions(session, portfolio_id) if other.id != transaction_id]
    try:
        validate_ledger(remaining)
    except OversoldLedgerError as error:
        raise OversoldError(error) from None

    session.delete(row)
    session.commit()


def ledger_events(transactions: list[Transaction]) -> list[LedgerEvent]:
    """Convert stored rows into the engine's input records."""
    return [_event(row) for row in transactions]


def _event(row: Transaction) -> LedgerEvent:
    return LedgerEvent(
        trade_date=row.trade_date,
        symbol=row.symbol,
        exchange=row.exchange,
        kind=row.kind,
        quantity=row.quantity,
        price=row.price,
        fees=row.fees,
    )
