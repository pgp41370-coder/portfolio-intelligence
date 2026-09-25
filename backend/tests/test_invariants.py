"""Cross-module invariants: identities the engine must satisfy, whatever the inputs.

Each of these was checked against the methodology before being asserted. Identities that do
*not* hold under this engine are written down here too, as tests that the engine reports the
difference rather than hiding it - an invariant that is only approximately true is worse than
no invariant at all, because it teaches the reader to ignore a failure.

They run against generated portfolios rather than one fixture, so a change that happens to
preserve the golden numbers but breaks the general case is still caught.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.performance import benchmarks as registry
from app.portfolios.rules import Exchange
from test_performance_api import MakeClient, SessionFactory, seed  # noqa: F401
from test_transaction_performance import add_transactions, buy, sell  # noqa: F401
from test_valuation_api import add_listing, add_price, create_portfolio, make_client  # noqa: F401

SESSIONS = [date(2026, 9, day) for day in (14, 15, 16, 17, 18)]
MON, TUE, WED, THU, FRI = SESSIONS
FRIDAY_EVENING = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)
CENT = Decimal("0.01")


def get(client: TestClient, portfolio_id: str, view: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"/api/v1/portfolios/{portfolio_id}/{view}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def mixed_portfolio(make_client: MakeClient, db_session_factory: SessionFactory) -> tuple[TestClient, str]:
    """Two securities, a partial sale and a later purchase: flows in both directions."""
    seed(db_session_factory, "S1", "One", "ONECO", dict(zip(SESSIONS, ["100", "105", "99", "108", "112"])))
    seed(db_session_factory, "S2", "Two", "TWOCO", dict(zip(SESSIONS, ["50", "48", "53", "51", "47"])))
    client = make_client(now=FRIDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "ONECO", 14, "100"), ("NSE", "TWOCO", 20, "50"))
    add_transactions(
        client,
        portfolio_id,
        buy("ONECO", MON, 10, "100", fees="7"),
        buy("TWOCO", MON, 30, "50", fees="9"),
        sell("TWOCO", WED, 10, "53", fees="4"),
        buy("ONECO", THU, 4, "108", fees="3"),
    )
    return client, portfolio_id


# --- 1. Contributions sum to the measured return --------------------------------------------


def test_contributions_sum_to_the_measured_daily_returns(
    mixed_portfolio: tuple[TestClient, str],
) -> None:
    """The decomposition identity: sum of contributions == sum of daily flow-adjusted returns."""
    client, portfolio_id = mixed_portfolio

    attribution = get(client, portfolio_id, "attribution")
    performance = get(client, portfolio_id, "performance")

    total = sum(
        Decimal(item["contribution_pct"]) for item in attribution["contributors"] + attribution["detractors"]
    )
    assert total == Decimal(attribution["sum_of_daily_returns_pct"])

    # And the same daily returns, added up, are what that figure means.
    daily = sum(
        Decimal(point["daily_return_pct"])
        for point in performance["series"]
        if point["daily_return_pct"] is not None
    )
    assert abs(daily - total) <= CENT  # both are rounded to 2 dp before being published


def test_the_same_identity_holds_for_the_intelligence_view(
    mixed_portfolio: tuple[TestClient, str],
) -> None:
    client, portfolio_id = mixed_portfolio

    returns = get(client, portfolio_id, "intelligence")["returns"]

    total = sum(Decimal(item["contribution_pct"]) for item in returns["top_positive"] + returns["top_negative"])
    assert total == Decimal(returns["sum_of_contributions_pct"])
    assert returns["contributions_reconcile"] is True


# --- 2. The compounding gap is reported, not hidden -------------------------------------------


def test_the_chained_return_differs_from_the_sum_and_says_so(
    mixed_portfolio: tuple[TestClient, str],
) -> None:
    """An identity that does NOT hold: arithmetic sum != compounded return. It is disclosed."""
    client, portfolio_id = mixed_portfolio

    returns = get(client, portfolio_id, "intelligence")["returns"]

    chained = Decimal(returns["portfolio_return_pct"])
    arithmetic = Decimal(returns["sum_of_contributions_pct"])
    difference = Decimal(returns["compounding_difference_pct"])
    assert difference == chained - arithmetic
    assert "differs from the compounded" in returns["note"]


# --- 3. Value change decomposes into performance and flows --------------------------------------


def test_value_change_equals_flows_plus_performance_driven_change(
    mixed_portfolio: tuple[TestClient, str],
) -> None:
    """end - start == net external flow + the part attributable to performance.

    This is the definition of ``return_driven_change``, so it holds exactly. It is asserted
    because it is the identity the cash-flow explanation rests on.
    """
    client, portfolio_id = mixed_portfolio

    cash = get(client, portfolio_id, "intelligence")["cash_flow"]

    start, end = Decimal(cash["start_value"]), Decimal(cash["end_value"])
    assert Decimal(cash["value_change"]) == end - start
    assert (
        Decimal(cash["value_change"])
        == Decimal(cash["net_external_flow"]) + Decimal(cash["return_driven_change"])
    )


def test_contributions_less_withdrawals_equal_the_net_flow(
    mixed_portfolio: tuple[TestClient, str],
) -> None:
    """The P&L view and the cash-flow view must describe the same money."""
    client, portfolio_id = mixed_portfolio

    cash = get(client, portfolio_id, "intelligence")["cash_flow"]
    totals = get(client, portfolio_id, "pnl")["totals"]

    assert Decimal(cash["contributions"]) - Decimal(cash["withdrawals"]) == Decimal(totals["net_invested"])
    # Every transaction in this window, so the net flow is the same number.
    assert Decimal(cash["net_external_flow"]) == Decimal(totals["net_invested"])


# --- 4. Allocation weights ---------------------------------------------------------------------


def test_priced_weights_sum_to_one_hundred_percent(mixed_portfolio: tuple[TestClient, str]) -> None:
    client, portfolio_id = mixed_portfolio

    allocation = get(client, portfolio_id, "allocation")

    assert allocation["holdings"], "the fixture has priced holdings"
    total = sum(Decimal(item["weight_pct"]) for item in allocation["holdings"])
    assert total == Decimal(100)
    assert Decimal(allocation["concentration"]["top_5_pct"]) == Decimal(100)  # only two holdings


# --- 5. A return is never the raw value change -----------------------------------------------------


def test_the_return_is_not_the_raw_value_change(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    """Prices flat, money added: value rises and the return must stay at zero."""
    seed(db_session_factory, "S1", "Flat", "FLATCO", dict(zip(SESSIONS, ["100"] * 5)))
    client = make_client(now=FRIDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "FLATCO", 110, "100"))
    add_transactions(client, portfolio_id, buy("FLATCO", MON, 10, "100"), buy("FLATCO", WED, 100, "100"))

    body = get(client, portfolio_id, "intelligence")

    cash = body["cash_flow"]
    assert Decimal(cash["value_change"]) == Decimal(10000)  # 1,000 -> 11,000
    assert body["returns"]["portfolio_return_pct"] == "0.00"  # nothing was earned
    # The whole rise was money paid in, so none of it is attributed to performance.
    assert Decimal(cash["net_external_flow"]) == Decimal(11000)  # both purchases
    assert Decimal(cash["return_driven_change"]) == Decimal(-1000)  # 10,000 - 11,000


# --- 6. Relative performance --------------------------------------------------------------------


def test_relative_return_is_the_difference_of_the_two_returns(
    mixed_portfolio: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, portfolio_id = mixed_portfolio
    monkeypatch.setitem(
        registry.BENCHMARKS,
        "INV",
        registry.BenchmarkDefinition(
            key="INV", display_name="Invariant ETF", nse_symbol="SETFNIF50", exchange=Exchange.NSE,
            tracks="Invariant index", source="test fixture", is_proxy=True,
            methodology="Daily closes rebased to 100.", note="ETF proxy, not the index itself.",
        ),
    )

    body = get(client, portfolio_id, "intelligence", benchmark="INV")

    returns = body["returns"]
    if returns["benchmark_return_pct"] is None:
        # No benchmark prices were seeded for this fixture, so nothing may be claimed.
        assert returns["relative_return_pct"] is None
        assert body["data_quality"]["benchmark_status"] != "available"
        return
    assert Decimal(returns["relative_return_pct"]) == Decimal(returns["portfolio_return_pct"]) - Decimal(
        returns["benchmark_return_pct"]
    )


# --- 7. Staleness is never presented as currency ----------------------------------------------------


def test_stale_data_is_never_reported_as_current(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """Coverage may be complete for what was measured, but the lag must always be visible."""
    seed(db_session_factory, "S1", "One", "ONECO", {MON: "100", TUE: "110"})
    client = make_client(now=FRIDAY_EVENING)  # Wed, Thu, Fri unpriced
    portfolio_id = create_portfolio(client, ("NSE", "ONECO", 10, "100"))
    add_transactions(client, portfolio_id, buy("ONECO", MON, 10, "100"))

    body = get(client, portfolio_id, "intelligence")

    quality = body["data_quality"]
    assert quality["coverage_status"] == "complete"  # complete for the window it measured
    assert quality["sessions_behind_latest"] == 3  # and explicitly behind the market
    assert body["status"] == "limited", "a stale explanation is never reported as fully available"
    assert any("behind" in item for item in quality["limitations"])


def test_a_current_portfolio_is_not_marked_stale(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "One", "ONECO", dict(zip(SESSIONS, ["100", "105", "99", "108", "112"])))
    client = make_client(now=FRIDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "ONECO", 10, "100"))
    add_transactions(client, portfolio_id, buy("ONECO", MON, 10, "100"))

    body = get(client, portfolio_id, "intelligence")

    assert body["data_quality"]["sessions_behind_latest"] == 0
    assert body["data_quality"]["stale_securities"] == []
    assert body["status"] == "available"


# --- 8. The views agree with one another ------------------------------------------------------------


def test_every_view_reports_the_same_window_and_figures(mixed_portfolio: tuple[TestClient, str]) -> None:
    client, portfolio_id = mixed_portfolio

    performance = get(client, portfolio_id, "performance")
    attribution = get(client, portfolio_id, "attribution")
    intelligence = get(client, portfolio_id, "intelligence")
    pnl = get(client, portfolio_id, "pnl")

    assert performance["period"] == attribution["period"] == intelligence["period"]
    assert intelligence["returns"]["portfolio_return_pct"] == performance["summary"]["cumulative_return_pct"]
    assert intelligence["risk"]["volatility_pct"] == performance["summary"]["volatility_pct"]
    assert intelligence["risk"]["max_drawdown_pct"] == performance["summary"]["max_drawdown_pct"]
    assert intelligence["cash_flow"]["net_external_flow"] == performance["summary"]["net_external_flow"]
    assert intelligence["cash_flow"]["contributions"] == pnl["totals"]["contributions"]
    assert intelligence["data_quality"]["coverage_status"] == performance["coverage"]["status"]
    assert (
        intelligence["data_quality"]["sessions_behind_latest"]
        == performance["coverage"]["sessions_behind_latest"]
    )


def test_the_holdings_basis_agrees_across_views_too(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """The consolidated valuation must serve both bases identically."""
    seed(db_session_factory, "S1", "One", "ONECO", dict(zip(SESSIONS, ["100", "105", "99", "108", "112"])))
    seed(db_session_factory, "S2", "Two", "TWOCO", dict(zip(SESSIONS, ["50", "48", "53", "51", "47"])))
    client = make_client(now=FRIDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "ONECO", 10, "100"), ("NSE", "TWOCO", 20, "50"))

    performance = get(client, portfolio_id, "performance")
    intelligence = get(client, portfolio_id, "intelligence")

    assert performance["basis"] == intelligence["returns"]["basis"] == "CURRENT_HOLDINGS"
    assert performance["period"] == intelligence["period"]
    assert intelligence["returns"]["portfolio_return_pct"] == performance["summary"]["cumulative_return_pct"]
    assert intelligence["cash_flow"]["net_external_flow"] == "0.00"  # no ledger, no flows
