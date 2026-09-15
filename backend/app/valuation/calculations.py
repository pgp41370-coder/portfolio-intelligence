"""Pure portfolio valuation arithmetic.

No database, HTTP or provider dependencies. Every monetary input and output is a
``Decimal``; floats are rejected. Results keep full precision and are rounded only when
serialised, using one policy:

* money: 2 decimal places, ROUND_HALF_UP
* percentages (returns and weights): 2 decimal places, ROUND_HALF_UP
* prices: shown exactly as stored (up to 4 decimal places)

Totals are computed from unrounded values, so a rounded total can differ by a paisa from
the sum of rounded rows.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

MONEY_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.01")
ROUNDING = ROUND_HALF_UP
_HUNDRED = Decimal(100)
_CONTEXT = Context(prec=34, rounding=ROUNDING)


@dataclass(frozen=True, slots=True)
class HoldingValue:
    invested_value: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_return_pct: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioTotals:
    total_invested_value: Decimal
    priced_invested_value: Decimal
    total_market_value: Decimal | None
    total_unrealized_pnl: Decimal | None
    total_unrealized_return_pct: Decimal | None
    priced_holding_count: int
    unpriced_holding_count: int

    @property
    def is_complete(self) -> bool:
        return self.unpriced_holding_count == 0


def invested_value(quantity: int, average_buy_price: Decimal) -> Decimal:
    """quantity × average buy price."""
    with localcontext(_CONTEXT):
        return Decimal(_quantity(quantity)) * _positive(average_buy_price, "average_buy_price")


def market_value(quantity: int, close_price: Decimal) -> Decimal:
    """quantity × end-of-day close price."""
    with localcontext(_CONTEXT):
        return Decimal(_quantity(quantity)) * _positive(close_price, "close_price")


def return_pct(pnl: Decimal, invested: Decimal) -> Decimal | None:
    """pnl ÷ invested × 100, or None when nothing was invested."""
    _decimal(pnl, "pnl")
    _decimal(invested, "invested")
    if invested <= 0:
        return None
    with localcontext(_CONTEXT):
        return pnl / invested * _HUNDRED


def value_holding(quantity: int, average_buy_price: Decimal, close_price: Decimal) -> HoldingValue:
    invested = invested_value(quantity, average_buy_price)
    market = market_value(quantity, close_price)
    with localcontext(_CONTEXT):
        pnl = market - invested
    pct = return_pct(pnl, invested)
    assert pct is not None  # invested is always positive here
    return HoldingValue(invested_value=invested, market_value=market, unrealized_pnl=pnl, unrealized_return_pct=pct)


def portfolio_totals(invested_values: Sequence[Decimal], priced: Sequence[HoldingValue]) -> PortfolioTotals:
    """Totals across all holdings (invested) and across priced holdings (value, P&L, return).

    Return is total P&L ÷ invested capital of the priced holdings, never an average of
    holding returns. Unpriced holdings contribute to total invested capital only.
    """
    if len(priced) > len(invested_values):
        raise ValueError("There cannot be more priced holdings than holdings.")
    with localcontext(_CONTEXT):
        total_invested = sum((_decimal(value, "invested_value") for value in invested_values), Decimal(0))
        if not priced:
            return PortfolioTotals(total_invested, Decimal(0), None, None, None, 0, len(invested_values))
        priced_invested = sum((holding.invested_value for holding in priced), Decimal(0))
        total_market = sum((holding.market_value for holding in priced), Decimal(0))
        pnl = total_market - priced_invested
    return PortfolioTotals(
        total_invested_value=total_invested,
        priced_invested_value=priced_invested,
        total_market_value=total_market,
        total_unrealized_pnl=pnl,
        total_unrealized_return_pct=return_pct(pnl, priced_invested),
        priced_holding_count=len(priced),
        unpriced_holding_count=len(invested_values) - len(priced),
    )


def weights_pct(market_values: Sequence[Decimal]) -> list[Decimal | None]:
    """Each market value as a percentage of their total; None for all when the total is not positive."""
    values = [_decimal(value, "market_value") for value in market_values]
    with localcontext(_CONTEXT):
        total = sum(values, Decimal(0))
        if total <= 0:
            return [None for _ in values]
        return [value / total * _HUNDRED for value in values]


def round_money(value: Decimal) -> Decimal:
    return _decimal(value, "value").quantize(MONEY_QUANTUM, rounding=ROUNDING)


def round_percent(value: Decimal) -> Decimal:
    return _decimal(value, "value").quantize(PERCENT_QUANTUM, rounding=ROUNDING)


def format_money(value: Decimal) -> str:
    return _plain(round_money(value))


def format_percent(value: Decimal) -> str:
    return _plain(round_percent(value))


def _plain(value: Decimal) -> str:
    return f"{abs(value) if value == 0 else value:f}"  # never "-0.00"


def _quantity(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("quantity must be an int.")
    if value <= 0:
        raise ValueError("quantity must be greater than 0.")
    return value


def _decimal(value: Decimal, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, not {type(value).__name__}.")
    if not value.is_finite():
        raise ValueError(f"{name} must be a finite number.")
    return value


def _positive(value: Decimal, name: str) -> Decimal:
    if _decimal(value, name) <= 0:
        raise ValueError(f"{name} must be greater than 0.")
    return value
