"""Pure performance arithmetic.

No database, HTTP or provider dependencies. Every monetary input is a ``Decimal`` and every
result keeps full precision until it is serialised, matching the valuation engine's policy.

Formulas (also documented in docs/performance.md):

* portfolio value        V_t = Σ (quantity_i × close_i,t)
* daily simple return    R_t = V_t / V_(t-1) − 1        (adjacent completed sessions only)
* cumulative return      V_T / V_0 − 1
* annualised volatility  stdev(R) × √252                (sample standard deviation)
* drawdown               DD_t = V_t / max(V_0..V_t) − 1
* maximum drawdown       min(DD_t)

A return is only computed between two sessions that are adjacent in the exchange calendar.
A pair separated by a missing session is skipped, never linked across the gap.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from enum import StrEnum

TRADING_DAYS_PER_YEAR = 252
MIN_RETURNS_FOR_VOLATILITY = 20
_CONTEXT = Context(prec=34, rounding=ROUND_HALF_UP)
_HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class ValuePoint:
    """One completely priced session."""

    trade_date: date
    value: Decimal


@dataclass(frozen=True, slots=True)
class ReturnPoint:
    trade_date: date
    value: Decimal
    daily_return: Decimal | None  # None when the previous session is missing
    cumulative_return: Decimal


def daily_returns(points: Sequence[ValuePoint], *, adjacent: Sequence[bool]) -> list[Decimal | None]:
    """Simple returns, one per point; the first is None, as is any pair spanning a gap.

    ``adjacent[i]`` states whether ``points[i-1]`` and ``points[i]`` are consecutive sessions
    in the exchange calendar.
    """
    if len(adjacent) != len(points):
        raise ValueError("adjacent must have one flag per point")
    returns: list[Decimal | None] = []
    with localcontext(_CONTEXT):
        for index, point in enumerate(points):
            previous = points[index - 1] if index else None
            if previous is None or not adjacent[index] or previous.value <= 0:
                returns.append(None)
            else:
                returns.append(point.value / previous.value - 1)
    return returns


def cumulative_return(start_value: Decimal, end_value: Decimal) -> Decimal | None:
    """End over start minus one. Valid across gaps: it uses two endpoints, not a chain."""
    if start_value <= 0:
        return None
    with localcontext(_CONTEXT):
        return end_value / start_value - 1


def annualised_volatility(returns: Sequence[Decimal | None]) -> Decimal | None:
    """Sample standard deviation of daily returns, scaled by √252.

    Returns None below ``MIN_RETURNS_FOR_VOLATILITY`` observations rather than publishing a
    figure that a handful of days could dominate.
    """
    observed = [value for value in returns if value is not None]
    if len(observed) < MIN_RETURNS_FOR_VOLATILITY:
        return None
    with localcontext(_CONTEXT):
        count = Decimal(len(observed))
        mean = sum(observed, Decimal(0)) / count
        variance = sum(((value - mean) ** 2 for value in observed), Decimal(0)) / (count - 1)
        return variance.sqrt() * Decimal(TRADING_DAYS_PER_YEAR).sqrt()


def drawdown_series(points: Sequence[ValuePoint]) -> list[Decimal]:
    """Each point's fall from the running peak; zero at a new peak."""
    series: list[Decimal] = []
    peak: Decimal | None = None
    with localcontext(_CONTEXT):
        for point in points:
            peak = point.value if peak is None or point.value > peak else peak
            series.append(point.value / peak - 1 if peak > 0 else Decimal(0))
    return series


def max_drawdown(points: Sequence[ValuePoint]) -> Decimal | None:
    """The worst peak-to-trough fall, as a negative number (0 if the series only rises)."""
    series = drawdown_series(points)
    return min(series) if series else None


def build_return_points(points: Sequence[ValuePoint], *, adjacent: Sequence[bool]) -> list[ReturnPoint]:
    """Value points enriched with daily and cumulative returns."""
    if not points:
        return []
    returns = daily_returns(points, adjacent=adjacent)
    base = points[0].value
    enriched: list[ReturnPoint] = []
    with localcontext(_CONTEXT):
        for point, change in zip(points, returns, strict=True):
            cumulative = (point.value / base - 1) if base > 0 else Decimal(0)
            enriched.append(ReturnPoint(point.trade_date, point.value, change, cumulative))
    return enriched


def as_percent(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    with localcontext(_CONTEXT):
        return value * _HUNDRED


# --- Flow-adjusted (time-weighted) return ---------------------------------------------------
#
# When money enters or leaves the portfolio, the change in value is no longer a return. The
# daily flow-adjusted return removes the flow before dividing:
#
#     R_t = (V_t - CF_t) / V_(t-1) - 1
#
# with CF_t the net external cash flow recognised at that session's close (buys positive, sells
# negative, fees included). Chaining these daily returns gives an exact time-weighted return:
# because the portfolio is valued every session, each sub-period is one day long, so no Modified
# Dietz weighting or assumption about when money arrived is involved.
#
# Statistics are then taken from a growth index built from those returns, never from raw value:
# otherwise a withdrawal would register as a drawdown.

INDEX_BASE = Decimal(100)


class ReturnSkip(StrEnum):
    GAP = "gap"  # the previous session was not valued
    ZERO_BASE = "zero_base"  # nothing was held, so no capital was at risk
    NEGATIVE_BASE = "negative_base"  # V_t - CF_t < 0: the input data cannot be right


@dataclass(frozen=True, slots=True)
class FlowAdjustedReturns:
    returns: list[Decimal | None]
    skips: list[ReturnSkip | None]

    @property
    def used(self) -> int:
        return sum(1 for value in self.returns if value is not None)

    def skipped(self, reason: ReturnSkip) -> int:
        return sum(1 for value in self.skips if value is reason)


def flow_adjusted_returns(
    points: Sequence[ValuePoint],
    *,
    adjacent: Sequence[bool],
    flows: Sequence[Decimal],
) -> FlowAdjustedReturns:
    """Daily time-weighted returns, one per point; the first is always None.

    ``flows[i]`` is the net external cash flow recognised at ``points[i]``. With flows of zero
    throughout, this reduces exactly to the simple daily return used for the M4.1 basis.
    """
    if not (len(adjacent) == len(points) == len(flows)):
        raise ValueError("points, adjacent and flows must be the same length")
    returns: list[Decimal | None] = []
    skips: list[ReturnSkip | None] = []
    with localcontext(_CONTEXT):
        for index, point in enumerate(points):
            previous = points[index - 1] if index else None
            if previous is None or not adjacent[index]:
                returns.append(None)
                skips.append(ReturnSkip.GAP if index else None)
                continue
            if previous.value <= 0:
                returns.append(None)
                skips.append(ReturnSkip.ZERO_BASE)
                continue
            adjusted = point.value - flows[index]
            if adjusted < 0:
                returns.append(None)
                skips.append(ReturnSkip.NEGATIVE_BASE)
                continue
            returns.append(adjusted / previous.value - 1)
            skips.append(None)
    return FlowAdjustedReturns(returns=returns, skips=skips)


def chain(returns: Sequence[Decimal | None]) -> Decimal | None:
    """Compound the daily returns: Pi (1 + R_t) - 1. None when no return could be measured."""
    observed = [value for value in returns if value is not None]
    if not observed:
        return None
    with localcontext(_CONTEXT):
        product = Decimal(1)
        for value in observed:
            product *= Decimal(1) + value
        return product - 1


def growth_index(points: Sequence[ValuePoint], returns: Sequence[Decimal | None]) -> list[ValuePoint]:
    """A base-100 index of compounded returns, aligned to the same sessions.

    Drawdown and volatility read this index rather than portfolio value, so contributions and
    withdrawals do not masquerade as performance. A day whose return could not be measured
    carries the index forward unchanged - it is a break in measurement, not a move.
    """
    index: list[ValuePoint] = []
    with localcontext(_CONTEXT):
        level = INDEX_BASE
        for point, change in zip(points, returns, strict=True):
            if change is not None:
                level *= Decimal(1) + change
            index.append(ValuePoint(point.trade_date, level))
    return index
