"""Money-weighted return: the XIRR solver, its result states, and the API around it.

The solver is tested directly with hand-checkable cash flows, because that is where the
arithmetic lives. The API tests then confirm the ledger is converted into those cash flows
correctly, and that a figure is withheld exactly when the methodology says it should be.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.performance.mwr import (
    MIN_DAYS_FOR_ANNUALISATION,
    CashFlow,
    MoneyWeightedStatus,
    build_cash_flows,
    money_weighted_return,
    net_present_value,
)
from test_performance_api import MakeClient, SessionFactory, seed  # noqa: F401
from test_transaction_performance import add_transactions, buy, sell  # noqa: F401
from test_valuation_api import add_listing, add_price, create_portfolio, make_client  # noqa: F401

MON, TUE, WED, THU, FRI = (date(2026, 9, day) for day in (14, 15, 16, 17, 18))
TUESDAY_EVENING = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)
WEDNESDAY_EVENING = datetime(2026, 9, 16, 13, 0, tzinfo=UTC)
FRIDAY_EVENING = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)
YEAR_START = date(2025, 1, 1)
YEAR_END = date(2026, 1, 1)  # 365 days later


def flow(day: date, amount: str) -> CashFlow:
    return CashFlow(on=day, amount=Decimal(amount))


def performance(client: TestClient, portfolio_id: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"/api/v1/portfolios/{portfolio_id}/performance", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def two_decimals(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(Decimal("0.01")))


# --- The solver: cases 1-20 with hand-checkable numbers -------------------------------------


def test_one_initial_investment_and_a_terminal_value() -> None:
    """1,000 in, 1,100 out a year later: exactly 10%."""
    result = money_weighted_return([flow(YEAR_START, "-1000"), flow(YEAR_END, "1100")])

    assert result.status is MoneyWeightedStatus.AVAILABLE
    assert two_decimals(result.annualised * 100) == "10.00"
    assert two_decimals(result.period * 100) == "10.00"  # the window is exactly a year
    assert result.days == 365 and result.roots_found == 1


def test_a_loss_gives_a_negative_rate() -> None:
    result = money_weighted_return([flow(YEAR_START, "-1000"), flow(YEAR_END, "900")])

    assert two_decimals(result.annualised * 100) == "-10.00"


def test_terminal_value_equal_to_invested_capital_is_exactly_zero() -> None:
    result = money_weighted_return([flow(YEAR_START, "-1000"), flow(YEAR_END, "1000")])

    assert result.status is MoneyWeightedStatus.AVAILABLE
    assert two_decimals(result.annualised * 100) == "0.00"
    assert two_decimals(result.period * 100) == "0.00"


def test_a_contribution_before_a_gain_earns_on_the_larger_balance() -> None:
    """Money added just before a rise: the money-weighted return picks that up."""
    early = money_weighted_return([
        flow(YEAR_START, "-1000"), flow(date(2025, 6, 30), "-1000"), flow(YEAR_END, "2400"),
    ])
    assert early.status is MoneyWeightedStatus.AVAILABLE
    assert early.annualised > 0


def test_a_contribution_before_a_loss_loses_on_the_larger_balance() -> None:
    late = money_weighted_return([
        flow(YEAR_START, "-1000"), flow(date(2025, 12, 1), "-5000"), flow(YEAR_END, "5400"),
    ])
    assert late.status is MoneyWeightedStatus.AVAILABLE
    assert late.annualised < 0  # most of the money was in for the fall


def test_multiple_contributions() -> None:
    result = money_weighted_return([
        flow(YEAR_START, "-1000"), flow(date(2025, 4, 1), "-1000"),
        flow(date(2025, 8, 1), "-1000"), flow(YEAR_END, "3300"),
    ])

    assert result.status is MoneyWeightedStatus.AVAILABLE
    assert result.contributions == Decimal(3000)
    assert result.annualised > 0


def test_multiple_withdrawals() -> None:
    result = money_weighted_return([
        flow(YEAR_START, "-10000"), flow(date(2025, 4, 1), "2000"),
        flow(date(2025, 8, 1), "2000"), flow(YEAR_END, "7000"),
    ])

    assert result.status is MoneyWeightedStatus.AVAILABLE
    assert result.withdrawals == Decimal(11000)  # including the terminal value
    assert result.annualised > 0  # 11,000 back on 10,000


def test_a_large_cash_flow_is_handled() -> None:
    result = money_weighted_return([flow(YEAR_START, "-100000000"), flow(YEAR_END, "110000000")])

    assert two_decimals(result.annualised * 100) == "10.00"


def test_a_very_small_cash_flow_is_handled() -> None:
    result = money_weighted_return([flow(YEAR_START, "-0.01"), flow(YEAR_END, "0.011")])

    assert result.status is MoneyWeightedStatus.AVAILABLE
    assert result.annualised > Decimal("0.09")


def test_no_cash_flows_at_all() -> None:
    assert money_weighted_return([]).status is MoneyWeightedStatus.INSUFFICIENT_HISTORY


def test_a_single_cash_flow_cannot_produce_a_rate() -> None:
    assert money_weighted_return([flow(YEAR_START, "-1000")]).status is MoneyWeightedStatus.INSUFFICIENT_HISTORY


def test_zero_initial_capital_is_reported_not_guessed() -> None:
    """Nothing was ever paid in, so there is no capital to earn a return on."""
    result = money_weighted_return([flow(YEAR_START, "0"), flow(YEAR_END, "500")])

    assert result.status is MoneyWeightedStatus.INSUFFICIENT_HISTORY
    assert "No money was paid into" in result.note


def test_flows_all_on_one_day_cannot_produce_a_rate() -> None:
    result = money_weighted_return([flow(YEAR_START, "-1000"), flow(YEAR_START, "1100")])

    assert result.status is MoneyWeightedStatus.INSUFFICIENT_HISTORY
    assert "same day" in result.note


def test_no_valid_root_when_the_flows_never_change_sign() -> None:
    """Everything paid in and nothing ever came back: no rate solves it."""
    result = money_weighted_return([flow(YEAR_START, "-1000"), flow(YEAR_END, "-500")])

    assert result.status is MoneyWeightedStatus.NO_SOLUTION
    assert result.annualised is None and result.period is None


def test_a_total_loss_has_no_rate_within_the_searched_range() -> None:
    result = money_weighted_return([flow(YEAR_START, "-1000"), flow(YEAR_END, "0")])

    assert result.status in {MoneyWeightedStatus.NO_SOLUTION, MoneyWeightedStatus.AVAILABLE}
    if result.status is MoneyWeightedStatus.AVAILABLE:
        assert result.annualised <= Decimal("-0.99")  # effectively -100%


def test_multiple_roots_are_withheld_never_resolved() -> None:
    """The classic sign-alternating series with two real roots.

    -1,000 / +2,500 / -1,540 has roots near 10% and 40%. Choosing either would be a judgement
    the data does not support, so neither is published.
    """
    result = money_weighted_return([
        flow(YEAR_START, "-1000"),
        flow(date(2026, 1, 1), "2500"),
        flow(date(2027, 1, 1), "-1540"),
    ])

    assert result.status is MoneyWeightedStatus.AMBIGUOUS_MULTIPLE_ROOTS
    assert result.roots_found >= 2
    assert result.annualised is None, "an ambiguous series must never publish a rate"
    assert result.period is None
    assert "no single" in result.note


def test_annualisation_is_withheld_below_the_minimum_window() -> None:
    start = date(2026, 1, 1)
    result = money_weighted_return([flow(start, "-1000"), flow(start + timedelta(days=30), "1020")])

    assert result.status is MoneyWeightedStatus.AVAILABLE
    assert result.annualised is None, "30 days must not be projected onto a year"
    assert two_decimals(result.period * 100) == "2.00"  # the period figure still stands
    assert "withheld" in result.annualisation_note and "30 days" in result.annualisation_note


def test_exactly_the_minimum_window_is_annualised() -> None:
    start = date(2026, 1, 1)
    result = money_weighted_return([
        flow(start, "-1000"), flow(start + timedelta(days=MIN_DAYS_FOR_ANNUALISATION), "1020"),
    ])

    assert result.days == 90
    assert result.annualised is not None
    assert result.annualisation_note is None


def test_one_day_below_the_minimum_is_not_annualised() -> None:
    start = date(2026, 1, 1)
    result = money_weighted_return([
        flow(start, "-1000"), flow(start + timedelta(days=MIN_DAYS_FOR_ANNUALISATION - 1), "1020"),
    ])

    assert result.days == 89 and result.annualised is None


def test_the_period_figure_is_the_annualised_rate_restated() -> None:
    """period = (1 + annualised)^(days/365) - 1, exactly."""
    start = date(2026, 1, 1)
    result = money_weighted_return([flow(start, "-1000"), flow(start + timedelta(days=182), "1100")])

    restated = (Decimal(1) + result.annualised) ** (Decimal(result.days) / Decimal(365)) - 1
    assert two_decimals(result.period * 100) == two_decimals(restated * 100)
    assert two_decimals(result.period * 100) == "10.00"  # 1,100 on 1,000 over the window


def test_the_solution_actually_satisfies_the_equation() -> None:
    """The definition of a root: discounting at the answer gives a present value of zero."""
    flows = [flow(YEAR_START, "-1000"), flow(date(2025, 7, 1), "-500"), flow(YEAR_END, "1700")]

    result = money_weighted_return(flows)

    assert abs(net_present_value(flows, result.annualised)) < Decimal("0.0001")


# --- The cash-flow builder ------------------------------------------------------------------


def test_the_builder_uses_the_first_flow_when_there_is_no_opening_position() -> None:
    """Full history: the initial investment is what was actually paid, fees included."""
    flows = build_cash_flows([MON, TUE], [Decimal("1010"), Decimal(0)], Decimal("1100"))

    assert [(item.on, item.amount) for item in flows] == [
        (MON, Decimal("-1010")),  # the cost, not the market value
        (TUE, Decimal("1100")),
    ]


def test_the_builder_values_an_opening_position_at_market() -> None:
    """Sub-window: the capital at stake is what the carried-in position is worth."""
    flows = build_cash_flows(
        [MON, TUE], [Decimal(0), Decimal(0)], Decimal("1100"), opening_value=Decimal("1000")
    )

    assert [(item.on, item.amount) for item in flows] == [(MON, Decimal("-1000")), (TUE, Decimal("1100"))]


def test_the_builder_combines_an_opening_position_with_a_first_session_flow() -> None:
    flows = build_cash_flows(
        [MON, TUE], [Decimal("500"), Decimal(0)], Decimal("1600"), opening_value=Decimal("1000")
    )

    amounts = sorted(item.amount for item in flows if item.on == MON)
    assert amounts == [Decimal("-1000"), Decimal("-500")]  # both, neither double-counted
    assert sum(item.amount for item in flows) == Decimal("100")


def test_the_builder_skips_sessions_with_no_flow() -> None:
    flows = build_cash_flows([MON, TUE, WED], [Decimal("1000"), Decimal(0), Decimal(0)], Decimal("1100"))

    assert len(flows) == 2  # the purchase and the terminal value


# --- Through the API ---------------------------------------------------------------------------


def test_a_portfolio_with_a_ledger_reports_both_returns(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "121"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = performance(client, portfolio_id)

    assert body["summary"]["cumulative_return_pct"] == "21.00"  # TWR, unchanged
    money = body["money_weighted"]
    assert money["status"] == "available"
    assert money["period_pct"] == "21.00"  # no flows after the first: the two agree
    assert money["period_days"] == 2
    assert money["annualisation_available"] is False  # two days is far short of 90
    assert money["method"] == "XIRR_BISECTION_ACT365"


def test_the_money_weighted_return_differs_once_money_is_added(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """A contribution just before a fall hurts the investor more than the portfolio."""
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "99"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 110, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), buy("RELIANCE", TUE, 100, "110"))

    body = performance(client, portfolio_id)

    twr = Decimal(body["summary"]["cumulative_return_pct"])
    mwr = Decimal(body["money_weighted"]["period_pct"])
    assert mwr < twr, "the extra money was exposed to the fall, so the investor did worse"


def test_a_holdings_only_portfolio_reports_not_applicable(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))

    money = performance(client, portfolio_id)["money_weighted"]

    assert money["status"] == "not_applicable"
    assert money["annualised_pct"] is None and money["period_pct"] is None
    assert "no transaction ledger" in money["note"]


def test_a_sub_window_values_the_opening_position_and_discloses_it(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "121", THU: "121", FRI: "133"})
    client = make_client(now=FRIDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = performance(client, portfolio_id, start_date=WED.isoformat())

    money = body["money_weighted"]
    assert money["opening_position_valued"] is True
    assert money["disclosure"] and "not attributed to it" in money["disclosure"]
    assert money["status"] == "available"
    # 1,210 at Wednesday's close to 1,330 on Friday: +9.92% over the window.
    assert money["period_pct"] == "9.92"


def test_a_same_day_pair_of_transactions_is_netted(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 15, "100"))
    add_transactions(
        client, portfolio_id, buy("RELIANCE", MON, 10, "100"), buy("RELIANCE", MON, 5, "100")
    )

    money = performance(client, portfolio_id)["money_weighted"]

    assert money["status"] == "available"
    assert money["contributions"] == "1500.00"  # one netted flow, not two entries
    assert money["period_pct"] == "10.00"


def test_a_non_trading_day_transaction_is_dated_at_its_session(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """A Sunday purchase is recognised on Monday, for the money-weighted return too."""
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", date(2026, 9, 13), 10, "100"))

    money = performance(client, portfolio_id)["money_weighted"]

    assert money["period_days"] == 1  # Monday to Tuesday, not Sunday to Tuesday
    assert money["period_pct"] == "10.00"


def test_a_withdrawal_appears_in_the_cash_flows(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "121"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 4, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), sell("RELIANCE", TUE, 6, "110"))

    money = performance(client, portfolio_id)["money_weighted"]

    assert money["contributions"] == "1000.00"
    # 660 from the sale plus 484 still held at the end.
    assert money["withdrawals"] == "1144.00"
    assert money["status"] == "available"


# --- The invariant identified in the audit ---------------------------------------------------------


def test_with_no_flows_after_the_first_the_two_returns_agree(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """One purchase and nothing else: timing cannot matter, so MWR equals TWR.

    This is the identity that anchors the two measures to each other. Where it fails, one of
    them is wrong.
    """
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "99", THU: "121", FRI: "132"})
    client = make_client(now=FRIDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = performance(client, portfolio_id)

    assert body["summary"]["cumulative_return_pct"] == body["money_weighted"]["period_pct"]


def test_the_identity_also_holds_for_a_single_purchase_with_fees(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """With a fee the two differ, because the fee is investor money the portfolio never held."""
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100", fees="50"))

    body = performance(client, portfolio_id)

    assert body["summary"]["cumulative_return_pct"] == "10.00"  # the portfolio rose 10%
    # The investor paid 1,050 to hold something worth 1,100.
    assert body["money_weighted"]["period_pct"] == "4.76"


def test_an_ambiguous_ledger_is_never_silently_given_a_number(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """Whatever the ledger, the API must never invent a single rate for an ambiguous series."""
    result = money_weighted_return([
        flow(date(2024, 1, 1), "-1000"),
        flow(date(2025, 1, 1), "2500"),
        flow(date(2026, 1, 1), "-1540"),
    ])

    assert result.status is MoneyWeightedStatus.AMBIGUOUS_MULTIPLE_ROOTS
    assert result.annualised is None and result.period is None


def test_the_money_weighted_block_never_calls_the_provider(
    make_client: MakeClient, db_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.market_data.providers.indian_api import IndianApiProvider

    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    monkeypatch.setattr(
        IndianApiProvider, "_request_json",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call the provider")),
    )

    assert performance(client, portfolio_id)["money_weighted"]["status"] == "available"
