"""Portfolio service: every read and write of portfolios and holdings goes through here."""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from psycopg import errors as pg_errors
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError
from app.portfolios.models import Holding, Portfolio
from app.portfolios.rules import MAX_HOLDINGS_PER_PORTFOLIO
from app.portfolios.schemas import HoldingInput, PortfolioCreate


class PortfolioNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(404, "portfolio_not_found", "Portfolio not found.")


class HoldingNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(404, "holding_not_found", "Holding not found in this portfolio.")


class DuplicateHoldingError(AppError):
    def __init__(self, symbol: str | None = None, exchange: str | None = None) -> None:
        message = (
            f"{symbol} on {exchange} is already in this portfolio."
            if symbol and exchange
            else "A holding is listed more than once in this portfolio."
        )
        super().__init__(409, "duplicate_holding", message)


class HoldingLimitError(AppError):
    def __init__(self) -> None:
        super().__init__(
            422,
            "holding_limit_reached",
            f"A portfolio can have at most {MAX_HOLDINGS_PER_PORTFOLIO} holdings.",
        )


@dataclass(frozen=True)
class PortfolioSummaryRow:
    portfolio: Portfolio
    holding_count: int
    total_invested_capital: Decimal


def create_portfolio(session: Session, data: PortfolioCreate) -> Portfolio:
    """Create a portfolio and all of its holdings in a single transaction."""
    portfolio = Portfolio(name=data.name, holdings=[_new_holding(item) for item in data.holdings])
    session.add(portfolio)
    _commit(session)
    session.refresh(portfolio, attribute_names=["holdings"])
    return portfolio


def list_portfolios(session: Session) -> list[PortfolioSummaryRow]:
    invested = func.coalesce(func.sum(Holding.quantity * Holding.average_buy_price), 0)
    statement = (
        select(Portfolio, func.count(Holding.id), invested)
        .outerjoin(Holding, Holding.portfolio_id == Portfolio.id)
        .group_by(Portfolio.id)
        .order_by(Portfolio.created_at.desc(), Portfolio.id)
    )
    return [
        PortfolioSummaryRow(portfolio, count, Decimal(total))
        for portfolio, count, total in session.execute(statement)
    ]


def get_portfolio(session: Session, portfolio_id: uuid.UUID) -> Portfolio:
    portfolio = session.get(Portfolio, portfolio_id, options=[selectinload(Portfolio.holdings)])
    if portfolio is None:
        raise PortfolioNotFoundError()
    return portfolio


def add_holding(session: Session, portfolio_id: uuid.UUID, data: HoldingInput) -> Holding:
    # Lock the portfolio row so concurrent requests cannot exceed the holding limit.
    portfolio = session.get(Portfolio, portfolio_id, with_for_update=True)
    if portfolio is None:
        raise PortfolioNotFoundError()

    holding_count = session.scalar(
        select(func.count()).select_from(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    if (holding_count or 0) >= MAX_HOLDINGS_PER_PORTFOLIO:
        raise HoldingLimitError()

    holding = _new_holding(data)
    holding.portfolio_id = portfolio_id
    session.add(holding)
    portfolio.updated_at = func.now()
    _commit(session, data)
    return holding


def delete_holding(session: Session, portfolio_id: uuid.UUID, holding_id: uuid.UUID) -> None:
    portfolio = session.get(Portfolio, portfolio_id, with_for_update=True)
    if portfolio is None:
        raise PortfolioNotFoundError()

    holding = session.scalar(
        select(Holding).where(Holding.id == holding_id, Holding.portfolio_id == portfolio_id)
    )
    if holding is None:
        raise HoldingNotFoundError()

    session.delete(holding)
    portfolio.updated_at = func.now()
    session.commit()


def _new_holding(data: HoldingInput) -> Holding:
    return Holding(
        symbol=data.symbol,
        exchange=data.exchange.value,
        quantity=data.quantity,
        average_buy_price=data.average_buy_price,
    )


def _commit(session: Session, holding: HoldingInput | None = None) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if isinstance(exc.orig, pg_errors.UniqueViolation):
            if holding is not None:
                raise DuplicateHoldingError(holding.symbol, holding.exchange.value) from None
            raise DuplicateHoldingError() from None
        raise
