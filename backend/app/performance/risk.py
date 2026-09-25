"""Risk statistics.

Every measure here states what it needs and returns ``None`` with a reason when it does not
have it. Nothing is published because it can be computed: a beta from eleven observations, or
a Sharpe ratio against an assumed risk-free rate, is a number that invites more confidence
than the data supports.

Minimum data requirements (also in docs/performance.md):

============================  =========================================================
Measure                       Requires
============================  =========================================================
Annualised volatility         >= 20 daily returns
Downside volatility           >= 20 daily returns, of which >= 5 below the threshold
Maximum drawdown              >= 2 valued sessions
Beta                          >= 20 paired portfolio/benchmark returns on the same days
Tracking error                >= 20 paired returns
Information ratio             tracking error > 0, and both cumulative returns available
Sharpe ratio                  a configured risk-free rate, plus volatility
============================  =========================================================
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

from app.performance.calculations import MIN_RETURNS_FOR_VOLATILITY, TRADING_DAYS_PER_YEAR

_CONTEXT = Context(prec=34, rounding=ROUND_HALF_UP)

MIN_PAIRED_RETURNS = 20
MIN_DOWNSIDE_OBSERVATIONS = 5


@dataclass(frozen=True, slots=True)
class Measure:
    """A statistic with the reason it is absent, when it is."""

    value: Decimal | None
    note: str | None = None

    @property
    def available(self) -> bool:
        return self.value is not None


def downside_volatility(
    returns: Sequence[Decimal | None], *, threshold: Decimal = Decimal(0)
) -> Measure:
    """Annualised standard deviation of returns below a threshold (default: zero).

    Uses the full observation count in the denominator, which is the standard downside
    deviation: days that were not losses still count as periods in which no loss occurred.
    """
    observed = [value for value in returns if value is not None]
    if len(observed) < MIN_RETURNS_FOR_VOLATILITY:
        return Measure(None, f"Needs at least {MIN_RETURNS_FOR_VOLATILITY} daily returns; {len(observed)} available.")
    below = [value for value in observed if value < threshold]
    if len(below) < MIN_DOWNSIDE_OBSERVATIONS:
        return Measure(
            None,
            f"Needs at least {MIN_DOWNSIDE_OBSERVATIONS} returns below the threshold; {len(below)} observed.",
        )
    with localcontext(_CONTEXT):
        squared = sum(((value - threshold) ** 2 for value in below), Decimal(0))
        variance = squared / Decimal(len(observed))
        return Measure(variance.sqrt() * Decimal(TRADING_DAYS_PER_YEAR).sqrt())


def paired_returns(
    portfolio: Sequence[Decimal | None], benchmark: Sequence[Decimal | None]
) -> tuple[list[Decimal], list[Decimal]]:
    """Returns for the days both series measured one. Never pads or aligns by position alone."""
    if len(portfolio) != len(benchmark):
        raise ValueError("series must be the same length")
    pairs = [(a, b) for a, b in zip(portfolio, benchmark, strict=True) if a is not None and b is not None]
    return [a for a, _ in pairs], [b for _, b in pairs]


def beta(portfolio: Sequence[Decimal], benchmark: Sequence[Decimal]) -> Measure:
    """Covariance(portfolio, benchmark) / variance(benchmark), on paired daily returns."""
    if len(portfolio) < MIN_PAIRED_RETURNS:
        return Measure(None, f"Needs at least {MIN_PAIRED_RETURNS} paired daily returns; {len(portfolio)} available.")
    with localcontext(_CONTEXT):
        count = Decimal(len(portfolio))
        mean_p = sum(portfolio, Decimal(0)) / count
        mean_b = sum(benchmark, Decimal(0)) / count
        covariance = sum(((p - mean_p) * (b - mean_b) for p, b in zip(portfolio, benchmark, strict=True)), Decimal(0))
        variance = sum(((b - mean_b) ** 2 for b in benchmark), Decimal(0))
        if variance == 0:
            return Measure(None, "The benchmark did not move over this window, so beta is undefined.")
        return Measure(covariance / variance)


def tracking_error(portfolio: Sequence[Decimal], benchmark: Sequence[Decimal]) -> Measure:
    """Annualised standard deviation of the daily return difference."""
    if len(portfolio) < MIN_PAIRED_RETURNS:
        return Measure(None, f"Needs at least {MIN_PAIRED_RETURNS} paired daily returns; {len(portfolio)} available.")
    with localcontext(_CONTEXT):
        differences = [p - b for p, b in zip(portfolio, benchmark, strict=True)]
        count = Decimal(len(differences))
        mean = sum(differences, Decimal(0)) / count
        variance = sum(((value - mean) ** 2 for value in differences), Decimal(0)) / (count - 1)
        return Measure(variance.sqrt() * Decimal(TRADING_DAYS_PER_YEAR).sqrt())


def information_ratio(excess_return: Decimal | None, tracking: Measure) -> Measure:
    """Excess return over the benchmark, divided by tracking error.

    Both are for the same window: the excess is the difference in cumulative return, and the
    tracking error is annualised, so this is a ratio of the window's outperformance to its
    consistency rather than a strictly annualised figure. The methodology note says so.
    """
    if excess_return is None:
        return Measure(None, "Needs a cumulative return for both the portfolio and the benchmark.")
    if not tracking.available:
        return Measure(None, tracking.note)
    if tracking.value == 0:
        return Measure(None, "Tracking error is zero, so the ratio is undefined.")
    with localcontext(_CONTEXT):
        return Measure(excess_return / tracking.value)


def sharpe_ratio(
    cumulative_return: Decimal | None,
    volatility: Decimal | None,
    *,
    risk_free_rate: Decimal | None,
    years: Decimal | None = None,
) -> Measure:
    """(annualised return - risk-free rate) / annualised volatility.

    Returns ``None`` unless a risk-free rate is configured. Assuming one - 6%, the 91-day
    T-bill, or zero - would manufacture precision the application does not have.
    """
    if risk_free_rate is None:
        return Measure(
            None,
            "No risk-free rate is configured. Set RISK_FREE_RATE_PCT to enable this measure; "
            "assuming a rate would manufacture precision.",
        )
    if cumulative_return is None or volatility is None:
        return Measure(None, "Needs both a cumulative return and an annualised volatility.")
    if volatility == 0:
        return Measure(None, "Volatility is zero, so the ratio is undefined.")
    with localcontext(_CONTEXT):
        if years and years > 0 and years != 1:
            # Annualise the window's return before comparing it with an annual rate.
            annualised = (Decimal(1) + cumulative_return) ** (Decimal(1) / years) - 1
        else:
            annualised = cumulative_return
        return Measure((annualised - risk_free_rate) / volatility)


@dataclass(frozen=True, slots=True)
class SessionCounts:
    """How the measured sessions split between gains, losses and flat days."""

    positive: int
    negative: int
    flat: int

    @property
    def measured(self) -> int:
        return self.positive + self.negative + self.flat


def session_counts(returns: Sequence[Decimal | None]) -> SessionCounts:
    """Count gaining, losing and unchanged sessions among the returns actually measured."""
    observed = [value for value in returns if value is not None]
    positive = sum(1 for value in observed if value > 0)
    negative = sum(1 for value in observed if value < 0)
    return SessionCounts(positive=positive, negative=negative, flat=len(observed) - positive - negative)


def current_drawdown(index_levels: Sequence[Decimal]) -> Measure:
    """How far the series sits below its own running peak right now.

    Zero means the latest value is the highest reached. Measured on the growth index, like the
    maximum drawdown, so a withdrawal never registers as a fall.
    """
    if not index_levels:
        return Measure(None, "Needs at least one valued session.")
    peak = max(index_levels)
    if peak <= 0:
        return Measure(None, "The series has no positive value to measure against.")
    with localcontext(_CONTEXT):
        return Measure(index_levels[-1] / peak - 1)
