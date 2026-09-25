"""Which securities moved the portfolio, and by how much.

This is the deterministic groundwork for portfolio intelligence: every explanation the
application can later give ("why did it fall today?", "why did it trail the benchmark?") should
be answerable from these numbers, not from a narrative invented after the fact.

**Definition.** A security's contribution on session ``t`` is its own value change with its cash
flow removed, measured against the whole portfolio's opening value:

    c_(i,t) = (V_(i,t) - V_(i,t-1) - CF_(i,t)) / V_(t-1)

Summed over securities this is exactly the portfolio's flow-adjusted daily return ``R_t``, which
makes the decomposition checkable rather than merely plausible - and a test asserts it.

**Over a window** the daily contributions are added. That arithmetic sum equals the sum of the
daily returns, which is **not** the chained time-weighted return: compounding makes the two
differ, more so the longer and more volatile the window. Both are reported, with the difference
named, instead of quietly presenting one as the other.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

from app.performance.positions import SecurityKey

_CONTEXT = Context(prec=34, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class DailyContribution:
    trade_date: date
    key: SecurityKey
    contribution: Decimal
    value_change: Decimal
    cash_flow: Decimal


@dataclass(frozen=True, slots=True)
class SecurityContribution:
    key: SecurityKey
    contribution: Decimal  # summed daily contributions over the window
    start_value: Decimal | None
    end_value: Decimal | None
    start_weight: Decimal | None
    end_weight: Decimal | None
    sessions_counted: int


@dataclass(frozen=True, slots=True)
class AttributionResult:
    securities: list[SecurityContribution]
    latest: list[DailyContribution]
    latest_date: date | None
    sum_of_daily_returns: Decimal | None
    sessions_counted: int

    @property
    def positive(self) -> list[SecurityContribution]:
        return [item for item in self.securities if item.contribution > 0]

    @property
    def negative(self) -> list[SecurityContribution]:
        return [item for item in self.securities if item.contribution < 0]


def attribute(
    *,
    sessions: Sequence[date],
    totals: Sequence[Decimal],
    values: dict[SecurityKey, Sequence[Decimal]],
    flows: dict[SecurityKey, Sequence[Decimal]],
    adjacent: Sequence[bool],
) -> AttributionResult:
    """Decompose the portfolio's return into per-security contributions.

    ``values`` and ``flows`` hold one entry per valued session for every security, zero where a
    security was not held. A session whose predecessor was not valued contributes nothing: the
    gap rule that governs returns governs attribution too.
    """
    if not sessions:
        return AttributionResult([], [], None, None, 0)

    keys = sorted(values)
    totals_by_key: dict[SecurityKey, Decimal] = {key: Decimal(0) for key in keys}
    counted_by_key: dict[SecurityKey, int] = {key: 0 for key in keys}
    latest: list[DailyContribution] = []
    latest_date: date | None = None
    total_return = Decimal(0)
    sessions_counted = 0

    with localcontext(_CONTEXT):
        for index in range(1, len(sessions)):
            base = totals[index - 1]
            if not adjacent[index] or base <= 0:
                continue
            sessions_counted += 1
            day_entries: list[DailyContribution] = []
            for key in keys:
                change = values[key][index] - values[key][index - 1]
                flow = flows[key][index]
                contribution = (change - flow) / base
                totals_by_key[key] += contribution
                if contribution != 0 or values[key][index] != 0:
                    counted_by_key[key] += 1
                day_entries.append(
                    DailyContribution(sessions[index], key, contribution, change, flow)
                )
                total_return += contribution
            latest, latest_date = day_entries, sessions[index]

    securities = [
        SecurityContribution(
            key=key,
            contribution=totals_by_key[key],
            start_value=values[key][0] if values[key] else None,
            end_value=values[key][-1] if values[key] else None,
            start_weight=_weight(values[key][0], totals[0]) if values[key] else None,
            end_weight=_weight(values[key][-1], totals[-1]) if values[key] else None,
            sessions_counted=counted_by_key[key],
        )
        for key in keys
    ]
    securities.sort(key=lambda item: (-item.contribution, item.key))
    latest.sort(key=lambda item: (-item.contribution, item.key))
    return AttributionResult(
        securities=securities,
        latest=latest,
        latest_date=latest_date,
        sum_of_daily_returns=total_return if sessions_counted else None,
        sessions_counted=sessions_counted,
    )


def benchmark_gap(
    portfolio_return: Decimal | None, benchmark_return: Decimal | None
) -> Decimal | None:
    """How far the portfolio finished ahead of or behind its benchmark, as a fraction."""
    if portfolio_return is None or benchmark_return is None:
        return None
    with localcontext(_CONTEXT):
        return portfolio_return - benchmark_return


def _weight(value: Decimal, total: Decimal) -> Decimal | None:
    if total <= 0:
        return None
    with localcontext(_CONTEXT):
        return value / total
