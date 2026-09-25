"""Pure performance arithmetic (no database)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.performance.calculations import (
    MIN_RETURNS_FOR_VOLATILITY,
    TRADING_DAYS_PER_YEAR,
    ValuePoint,
    annualised_volatility,
    as_percent,
    build_return_points,
    cumulative_return,
    daily_returns,
    drawdown_series,
    max_drawdown,
)

DAY = date(2026, 9, 14)


def points(*values: str, start: date = DAY) -> list[ValuePoint]:
    return [ValuePoint(start + timedelta(days=index), Decimal(value)) for index, value in enumerate(values)]


def all_adjacent(count: int) -> list[bool]:
    return [False] + [True] * (count - 1)


def test_ten_percent_move_gives_ten_percent_return() -> None:
    series = points("1000", "1100")

    returns = daily_returns(series, adjacent=all_adjacent(2))

    assert returns[0] is None
    assert returns[1] == Decimal("0.1")
    assert as_percent(returns[1]) == Decimal("10")


def test_cumulative_return_uses_endpoints() -> None:
    assert cumulative_return(Decimal("1000"), Decimal("1210")) == Decimal("0.21")
    assert cumulative_return(Decimal("1000"), Decimal("900")) == Decimal("-0.1")


def test_cumulative_return_is_undefined_without_a_positive_start() -> None:
    assert cumulative_return(Decimal("0"), Decimal("100")) is None
    assert cumulative_return(Decimal("-5"), Decimal("100")) is None


def test_returns_are_never_linked_across_a_gap() -> None:
    series = points("1000", "1100", "1210")
    adjacent = [False, True, False]  # the third session follows a missing day

    returns = daily_returns(series, adjacent=adjacent)

    assert returns[1] == Decimal("0.1")
    assert returns[2] is None  # not (1210/1100 - 1): the pair spans a gap


def test_cumulative_return_still_spans_a_gap_because_it_uses_two_endpoints() -> None:
    series = points("1000", "1100", "1210")

    enriched = build_return_points(series, adjacent=[False, True, False])

    assert enriched[-1].cumulative_return == Decimal("0.21")
    assert enriched[-1].daily_return is None


def test_volatility_needs_a_minimum_number_of_observations() -> None:
    few = [Decimal("0.01")] * (MIN_RETURNS_FOR_VOLATILITY - 1)

    assert annualised_volatility(few) is None
    assert annualised_volatility([]) is None
    assert annualised_volatility([None, None]) is None


def test_constant_returns_have_zero_volatility() -> None:
    steady = [Decimal("0.01")] * MIN_RETURNS_FOR_VOLATILITY

    assert annualised_volatility(steady) == Decimal(0)


def test_volatility_is_annualised_by_root_252() -> None:
    alternating = [Decimal("0.02") if index % 2 else Decimal("-0.02") for index in range(MIN_RETURNS_FOR_VOLATILITY)]

    volatility = annualised_volatility(alternating)

    assert volatility is not None
    # sample stdev of ±2% about zero is ~0.0205; annualised ≈ 0.0205 × √252 ≈ 0.3256
    assert Decimal("0.30") < volatility < Decimal("0.35")
    assert TRADING_DAYS_PER_YEAR == 252


def test_volatility_ignores_gap_returns() -> None:
    with_gaps = [None] + [Decimal("0.01")] * MIN_RETURNS_FOR_VOLATILITY

    assert annualised_volatility(with_gaps) == Decimal(0)


def test_drawdown_measures_the_fall_from_the_running_peak() -> None:
    series = points("100", "120", "90", "150")

    drawdowns = drawdown_series(series)

    assert drawdowns[0] == Decimal(0)
    assert drawdowns[1] == Decimal(0)  # new peak
    assert drawdowns[2] == Decimal("-0.25")  # 90 / 120 - 1
    assert drawdowns[3] == Decimal(0)
    assert max_drawdown(series) == Decimal("-0.25")


def test_a_rising_series_has_no_drawdown() -> None:
    assert max_drawdown(points("100", "110", "120")) == Decimal(0)
    assert max_drawdown([]) is None


def test_return_points_carry_value_daily_and_cumulative() -> None:
    enriched = build_return_points(points("1000", "1100", "1210"), adjacent=all_adjacent(3))

    assert [point.value for point in enriched] == [Decimal("1000"), Decimal("1100"), Decimal("1210")]
    assert enriched[1].daily_return == Decimal("0.1")
    assert enriched[2].cumulative_return == Decimal("0.21")


def test_adjacency_flags_must_match_the_points() -> None:
    with pytest.raises(ValueError):
        daily_returns(points("100", "110"), adjacent=[False])
