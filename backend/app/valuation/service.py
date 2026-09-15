"""Portfolio valuation: stored holdings × stored NSE end-of-day closing prices.

Reads the database only. It never calls a market-data provider, never infers a price and
never substitutes zero for a missing one.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.market_data.calendar import PriceFreshness, classify_freshness, latest_expected_session
from app.market_data.providers import provider_display_name
from app.market_data.records import UnpricedReason
from app.market_data.service import PriceLookup, PricePoint, lookup_latest_prices
from app.portfolios.models import Holding
from app.portfolios.rules import Exchange
from app.portfolios.service import get_portfolio
from app.valuation.calculations import (
    HoldingValue,
    display_weights_pct,
    invested_value,
    portfolio_totals,
    value_holding,
    weights_pct,
)
from app.valuation.schemas import (
    FreshnessSummaryRead,
    HoldingValuationRead,
    HoldingWarning,
    MethodologyRead,
    PortfolioValuationRead,
    PriceRead,
    ValuationStatus,
    ValuationTotalsRead,
)

# A day-over-day close move of 35% or more usually means a split or bonus issue, which
# would make P&L against the user's average buy price misleading.
LARGE_PRICE_MOVE_THRESHOLD = Decimal("0.35")


@dataclass(frozen=True, slots=True)
class _Row:
    holding: Holding
    invested: Decimal
    status: ValuationStatus
    unpriced_reason: UnpricedReason | None
    price: PricePoint | None
    value: HoldingValue | None
    warnings: list[HoldingWarning]


def value_portfolio(
    session: Session,
    portfolio_id: uuid.UUID,
    *,
    settings: Settings,
    now: datetime,
) -> PortfolioValuationRead:
    portfolio = get_portfolio(session, portfolio_id)
    expected = latest_expected_session(now, settings.trading_calendar)
    lookups = lookup_latest_prices(
        session,
        settings.market_data_provider,
        {(Exchange(holding.exchange), holding.symbol) for holding in portfolio.holdings},
    )

    rows: list[_Row] = []
    for holding in portfolio.holdings:
        lookup = lookups[(Exchange(holding.exchange), holding.symbol)]
        invested = invested_value(holding.quantity, holding.average_buy_price)
        if lookup.latest is None:
            rows.append(_Row(holding, invested, ValuationStatus.UNPRICED, lookup.unpriced_reason, None, None, []))
            continue
        value = value_holding(holding.quantity, holding.average_buy_price, lookup.latest.close_price)
        fresh = classify_freshness(lookup.latest.trade_date, expected) is PriceFreshness.FRESH
        rows.append(
            _Row(
                holding,
                invested,
                ValuationStatus.VALUED if fresh else ValuationStatus.STALE,
                None,
                lookup.latest,
                value,
                _warnings(lookup),
            )
        )

    priced_values = [row.value for row in rows if row.value is not None]
    exact_weights = weights_pct([value.market_value for value in priced_values])
    # Displayed weights are allocated after rounding so that they sum to exactly 100.00.
    positive_weights = [weight for weight in exact_weights if weight is not None]
    shown_weights = display_weights_pct(positive_weights) if len(positive_weights) == len(exact_weights) else exact_weights
    weights = iter(shown_weights)
    totals = portfolio_totals([row.invested for row in rows], priced_values)
    price_dates = [row.price.trade_date for row in rows if row.price is not None]

    return PortfolioValuationRead(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        valued_at=now,
        market_data_configured=settings.market_data_configured,
        methodology=MethodologyRead(),
        freshness=FreshnessSummaryRead(
            expected_session_date=expected,
            latest_price_date=max(price_dates) if price_dates else None,
            oldest_price_date=min(price_dates) if price_dates else None,
            valued_count=sum(1 for row in rows if row.status is ValuationStatus.VALUED),
            stale_count=sum(1 for row in rows if row.status is ValuationStatus.STALE),
            unpriced_count=sum(1 for row in rows if row.status is ValuationStatus.UNPRICED),
        ),
        totals=ValuationTotalsRead(
            total_invested_value=totals.total_invested_value,
            priced_invested_value=totals.priced_invested_value,
            total_market_value=totals.total_market_value,
            total_unrealized_pnl=totals.total_unrealized_pnl,
            total_unrealized_return_pct=totals.total_unrealized_return_pct,
            is_complete=totals.is_complete,
        ),
        holdings=[_holding_read(row, next(weights) if row.value is not None else None) for row in rows],
    )


def _holding_read(row: _Row, weight: Decimal | None) -> HoldingValuationRead:
    price = row.price
    value = row.value
    return HoldingValuationRead(
        holding_id=row.holding.id,
        symbol=row.holding.symbol,
        exchange=Exchange(row.holding.exchange),
        quantity=row.holding.quantity,
        average_buy_price=row.holding.average_buy_price,
        status=row.status,
        unpriced_reason=row.unpriced_reason,
        price=PriceRead(
            close_price=price.close_price,
            trade_date=price.trade_date,
            exchange=price.exchange,
            source=price.source,
            source_name=provider_display_name(price.source),
            fetched_at=price.fetched_at,
        )
        if price is not None
        else None,
        invested_value=row.invested,
        market_value=value.market_value if value else None,
        unrealized_pnl=value.unrealized_pnl if value else None,
        unrealized_return_pct=value.unrealized_return_pct if value else None,
        weight_pct=weight,
        warnings=row.warnings,
    )


def _warnings(lookup: PriceLookup) -> list[HoldingWarning]:
    if lookup.latest is None or lookup.previous is None:
        return []
    change = (lookup.latest.close_price - lookup.previous.close_price) / lookup.previous.close_price
    return [HoldingWarning.LARGE_PRICE_MOVE] if abs(change) >= LARGE_PRICE_MOVE_THRESHOLD else []
