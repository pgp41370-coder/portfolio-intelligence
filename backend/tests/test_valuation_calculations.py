"""Pure Decimal valuation arithmetic (no database)."""

from decimal import Decimal

import pytest

from app.valuation.calculations import (
    HoldingValue,
    display_weights_pct,
    format_money,
    format_percent,
    invested_value,
    market_value,
    portfolio_totals,
    return_pct,
    round_money,
    round_percent,
    value_holding,
    weights_pct,
)


def test_methodology_example_reliance() -> None:
    # 10 shares bought at ₹2,400, valued at the ₹2,650 NSE close.
    value = value_holding(10, Decimal("2400"), Decimal("2650"))

    assert value.invested_value == Decimal("24000")
    assert value.market_value == Decimal("26500")
    assert value.unrealized_pnl == Decimal("2500")
    assert value.unrealized_return_pct.quantize(Decimal("0.000000001")) == Decimal("10.416666667")
    assert round_percent(value.unrealized_return_pct) == Decimal("10.42")
    assert format_percent(value.unrealized_return_pct) == "10.42"
    assert str(value.unrealized_return_pct).startswith("10.41666666")


def test_invested_and_market_value_are_exact_with_four_decimal_prices() -> None:
    assert invested_value(3, Decimal("1650.3333")) == Decimal("4950.9999")
    assert market_value(7, Decimal("0.0500")) == Decimal("0.3500")


def test_losses_and_break_even() -> None:
    loss = value_holding(6, Decimal("3500"), Decimal("3000"))
    assert loss.unrealized_pnl == Decimal("-3000")
    assert format_percent(loss.unrealized_return_pct) == "-14.29"

    even = value_holding(5, Decimal("100"), Decimal("100"))
    assert even.unrealized_pnl == 0
    assert format_money(even.unrealized_pnl) == "0.00"


def test_portfolio_totals_use_aggregate_pnl_over_priced_invested_capital() -> None:
    reliance = value_holding(10, Decimal("2400"), Decimal("2700"))  # +3,000 on 24,000
    tcs = value_holding(6, Decimal("3500"), Decimal("3000"))  # -3,000 on 21,000
    unpriced_invested = invested_value(4, Decimal("1000"))

    totals = portfolio_totals(
        [reliance.invested_value, tcs.invested_value, unpriced_invested],
        [reliance, tcs],
    )

    assert totals.total_invested_value == Decimal("49000")
    assert totals.priced_invested_value == Decimal("45000")
    assert totals.total_market_value == Decimal("45000")
    assert totals.total_unrealized_pnl == Decimal("0")
    assert totals.total_unrealized_return_pct == Decimal("0")
    assert totals.priced_holding_count == 2
    assert totals.unpriced_holding_count == 1
    assert totals.is_complete is False


def test_portfolio_return_is_not_an_average_of_holding_returns() -> None:
    small = value_holding(1, Decimal("100"), Decimal("200"))  # +100%
    large = value_holding(100, Decimal("100"), Decimal("90"))  # -10%

    totals = portfolio_totals([small.invested_value, large.invested_value], [small, large])

    # (100 - 1,000) / 10,100 = -8.91%, not (100% - 10%) / 2 = 45%.
    assert format_percent(totals.total_unrealized_return_pct or Decimal(0)) == "-8.91"


def test_totals_without_prices_have_no_market_value() -> None:
    totals = portfolio_totals([Decimal("24000")], [])

    assert totals.total_invested_value == Decimal("24000")
    assert totals.total_market_value is None
    assert totals.total_unrealized_pnl is None
    assert totals.total_unrealized_return_pct is None
    assert totals.is_complete is False


def test_empty_portfolio_totals() -> None:
    totals = portfolio_totals([], [])

    assert totals.total_invested_value == 0
    assert totals.total_market_value is None
    assert totals.is_complete is True


def test_weights_are_market_value_shares() -> None:
    weights = weights_pct([Decimal("27000"), Decimal("18000")])

    assert weights == [Decimal("60"), Decimal("40")]
    thirds = weights_pct([Decimal("1"), Decimal("1"), Decimal("1")])
    assert [format_percent(weight or Decimal(0)) for weight in thirds] == ["33.33", "33.33", "33.33"]


def test_displayed_weights_sum_to_exactly_100_by_largest_remainder() -> None:
    thirds = display_weights_pct(weights_pct([Decimal("1"), Decimal("1"), Decimal("1")]))

    assert thirds == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]  # tie: earliest position
    assert sum(thirds) == Decimal("100.00")
    assert display_weights_pct(weights_pct([Decimal("5"), Decimal("5")])) == [Decimal("50.00"), Decimal("50.00")]
    assert display_weights_pct(weights_pct([Decimal("26500")])) == [Decimal("100.00")]
    assert display_weights_pct([]) == []


def test_displayed_weights_fix_the_real_validation_portfolio() -> None:
    # M3A.1 real-data portfolio: 4 x 1235.30, 6 x 716.55, 3 x 3029.50. Rounding each weight
    # separately gives 26.96 + 23.46 + 49.59 = 100.01.
    exact = weights_pct([Decimal("4941.20"), Decimal("4299.30"), Decimal("9088.50")])
    assert sum(round_percent(weight or Decimal(0)) for weight in exact) == Decimal("100.01")

    shown = display_weights_pct([weight or Decimal(0) for weight in exact])

    assert shown == [Decimal("26.96"), Decimal("23.46"), Decimal("49.58")]
    assert sum(shown) == Decimal("100.00")
    assert all(abs(displayed - (weight or Decimal(0))) < Decimal("0.01") for displayed, weight in zip(shown, exact, strict=True))


def test_displayed_weights_reject_inputs_that_are_not_shares_of_100() -> None:
    with pytest.raises(ValueError):
        display_weights_pct([Decimal("40"), Decimal("40")])
    with pytest.raises(TypeError):
        display_weights_pct([50.0, 50.0])  # type: ignore[list-item]


def test_weights_are_undefined_without_positive_total() -> None:
    assert weights_pct([Decimal("0"), Decimal("0")]) == [None, None]
    assert weights_pct([]) == []


def test_return_pct_is_undefined_without_invested_capital() -> None:
    assert return_pct(Decimal("10"), Decimal("0")) is None


@pytest.mark.parametrize(
    ("quantity", "average", "close", "error"),
    [
        (0, Decimal("1"), Decimal("1"), ValueError),
        (-1, Decimal("1"), Decimal("1"), ValueError),
        (True, Decimal("1"), Decimal("1"), TypeError),
        (1.5, Decimal("1"), Decimal("1"), TypeError),
        (1, 2400.0, Decimal("1"), TypeError),
        (1, Decimal("1"), 2650.0, TypeError),
        (1, Decimal("0"), Decimal("1"), ValueError),
        (1, Decimal("1"), Decimal("0"), ValueError),
        (1, Decimal("1"), Decimal("-5"), ValueError),
        (1, Decimal("NaN"), Decimal("1"), ValueError),
        (1, Decimal("1"), Decimal("Infinity"), ValueError),
    ],
)
def test_invalid_inputs_are_rejected(quantity: object, average: object, close: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        value_holding(quantity, average, close)  # type: ignore[arg-type]


def test_rounding_policy_is_half_up_to_two_places() -> None:
    assert round_money(Decimal("0.005")) == Decimal("0.01")
    assert round_money(Decimal("0.004999")) == Decimal("0.00")
    assert round_money(Decimal("-0.005")) == Decimal("-0.01")
    assert round_percent(Decimal("10.415")) == Decimal("10.42")
    assert format_money(Decimal("-0.001")) == "0.00"
    assert format_money(Decimal("26500")) == "26500.00"


def test_large_values_keep_precision() -> None:
    value = value_holding(1_000_000_000, Decimal("9999999999.9999"), Decimal("9999999999.9999"))

    # 1,000,000,000 × 9,999,999,999.9999 is exactly 9,999,999,999,999,900,000.
    assert value.market_value == Decimal("9999999999999900000")
    assert format_money(value.market_value) == "9999999999999900000.00"
    assert value.unrealized_pnl == 0
    assert isinstance(value, HoldingValue)
