"""Golden values: a frozen portfolio whose every published figure is pinned.

These tests exist to make a silent change in the financial methodology impossible. They do not
check that the maths is *good* - the arithmetic tests elsewhere do that - they check that it is
*unchanged*. If one of these fails, either a calculation moved or the fixture did, and both
deserve an explanation before the number is updated.

The fixture mirrors the shape of the development portfolio that was validated against raw SQL:
several securities, a partial sale, a late purchase, fees, and a benchmark.

Every expected value below was derived from the fixture prices by an independent script that
imports none of the application, not copied from a previous run. The derivation is written
beside each one.
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

# Mon 14 Sep to Fri 18 Sep 2026: five consecutive sessions under the default weekday calendar.
MON, TUE, WED, THU, FRI = (date(2026, 9, day) for day in (14, 15, 16, 17, 18))
FRIDAY_EVENING = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)

# ALPHA: 100 -> 110 -> 121 -> 121 -> 132.  BETA: 200 -> 180 -> 190 -> 200 -> 190.
ALPHA_PRICES = {MON: "100", TUE: "110", WED: "121", THU: "121", FRI: "132"}
BETA_PRICES = {MON: "200", TUE: "180", WED: "190", THU: "200", FRI: "190"}
# The benchmark proxy: 1,000 -> 1,010 -> 1,020 -> 1,030 -> 1,040 (a steady +4.00% over the window).
BENCHMARK_PRICES = {MON: "1000", TUE: "1010", WED: "1020", THU: "1030", FRI: "1040"}


@pytest.fixture
def golden_portfolio(
    make_client: MakeClient, db_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, str]:
    """A portfolio with a partial sale, a later purchase and fees, priced across five sessions."""
    seed(db_session_factory, "S1", "Alpha", "ALPHA", ALPHA_PRICES)
    seed(db_session_factory, "S2", "Beta", "BETA", BETA_PRICES)
    seed(db_session_factory, "S3", "Index ETF", "SETFNIF50", BENCHMARK_PRICES)
    monkeypatch.setitem(
        registry.BENCHMARKS,
        "GOLDEN",
        registry.BenchmarkDefinition(
            key="GOLDEN",
            display_name="Golden index ETF",
            nse_symbol="SETFNIF50",
            exchange=Exchange.NSE,
            tracks="Golden index",
            source="test fixture",
            is_proxy=True,
            methodology="Daily closes rebased to 100.",
            note="ETF proxy, not the index itself.",
        ),
    )
    client = make_client(now=FRIDAY_EVENING)
    # Closing position: ALPHA 10 + 5 = 15, BETA 10 - 6 = 4.
    portfolio_id = create_portfolio(client, ("NSE", "ALPHA", 15, "100"), ("NSE", "BETA", 4, "200"))
    add_transactions(
        client,
        portfolio_id,
        buy("ALPHA", MON, 10, "100", fees="10"),
        buy("BETA", MON, 10, "200", fees="20"),
        sell("BETA", WED, 6, "190", fees="6"),
        buy("ALPHA", THU, 5, "121", fees="5"),
    )
    return client, portfolio_id


def get(client: TestClient, portfolio_id: str, view: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"/api/v1/portfolios/{portfolio_id}/{view}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --- The value series the whole thing rests on --------------------------------------------


def test_golden_value_series(golden_portfolio: tuple[TestClient, str]) -> None:
    """Every later figure is derived from these five numbers, so they are pinned first."""
    client, portfolio_id = golden_portfolio

    series = get(client, portfolio_id, "performance")["series"]

    assert [point["trade_date"] for point in series] == [
        "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    ]
    assert [point["value"] for point in series] == [
        "3000.00",  # Mon: 10 x 100 + 10 x 200
        "2900.00",  # Tue: 10 x 110 + 10 x 180
        "1970.00",  # Wed: 10 x 121 + 4 x 190  (six BETA sold at the close)
        "2615.00",  # Thu: 15 x 121 + 4 x 200  (five ALPHA bought at the close)
        "2740.00",  # Fri: 15 x 132 + 4 x 190
    ]


def test_golden_time_weighted_return(golden_portfolio: tuple[TestClient, str]) -> None:
    """R_t = (V_t - CF_t) / V_(t-1) - 1, chained.

    Tue: (2900 - 0) / 3000 - 1            = -3.3333%
    Wed: (1970 - (-1134)) / 2900 - 1      = +7.0345%   (sale proceeds 6x190 - 6 = 1,134)
    Thu: (2615 - 610) / 1970 - 1          = +1.7766%   (purchase 5x121 + 5 = 610)
    Fri: (2740 - 0) / 2615 - 1            = +4.7801%
    Product - 1                           = +10.34%
    """
    client, portfolio_id = golden_portfolio

    summary = get(client, portfolio_id, "performance")["summary"]

    assert summary["start_value"] == "3000.00"
    assert summary["end_value"] == "2740.00"
    assert summary["cumulative_return_pct"] == "10.34"
    assert summary["returns_used"] == 4
    assert summary["returns_skipped_across_gaps"] == 0
    # 1,010 + 2,020 in on Monday, 1,134 out on Wednesday, 610 in on Thursday.
    assert summary["net_external_flow"] == "2506.00"


def test_golden_intelligence_headline_figures(golden_portfolio: tuple[TestClient, str]) -> None:
    client, portfolio_id = golden_portfolio

    body = get(client, portfolio_id, "intelligence", benchmark="GOLDEN")

    returns = body["returns"]
    assert returns["portfolio_return_pct"] == "10.34"
    assert returns["benchmark_return_pct"] == "4.00"  # 1,040 / 1,000 - 1
    assert returns["relative_return_pct"] == "6.34"  # 10.34 - 4.00
    assert returns["calculation_method"] == "TWR_DAILY_CHAINED"
    assert returns["basis"] == "TRANSACTIONS"
    assert body["data_quality"]["benchmark_basis"] == "ETF_PROXY"


def test_golden_contributions(golden_portfolio: tuple[TestClient, str]) -> None:
    """Per security, summed over the four measured sessions.

    ALPHA: 100/3000 + 110/2900 + (-5)/1970 + 165/2615     = +13.18 pts
    BETA:  -200/3000 + 94/2900 + 40/1970 + (-40)/2615     = -2.92 pts
    (BETA's Wednesday value falls 1,040 against a -1,134 flow, so +94 net.)
    """
    client, portfolio_id = golden_portfolio

    returns = get(client, portfolio_id, "intelligence", benchmark="GOLDEN")["returns"]

    contributions = {
        item["symbol"]: item["contribution_pct"] for item in returns["top_positive"] + returns["top_negative"]
    }
    assert contributions == {"ALPHA": "13.18", "BETA": "-2.92"}
    assert [item["symbol"] for item in returns["top_positive"]] == ["ALPHA"]
    assert [item["symbol"] for item in returns["top_negative"]] == ["BETA"]
    assert [item["rank"] for item in returns["top_positive"]] == [1]
    assert returns["sum_of_contributions_pct"] == "10.26"
    # The compounded return is 10.34: the 0.08 difference is compounding, and it is reported.
    assert returns["compounding_difference_pct"] == "0.08"
    assert returns["contributions_reconcile"] is True


def test_golden_security_price_returns(golden_portfolio: tuple[TestClient, str]) -> None:
    """A security's own price return, which is not the same thing as its contribution."""
    client, portfolio_id = golden_portfolio

    returns = get(client, portfolio_id, "intelligence", benchmark="GOLDEN")["returns"]

    by_symbol = {item["symbol"]: item for item in returns["top_positive"] + returns["top_negative"]}
    assert by_symbol["ALPHA"]["security_return_pct"] == "32.00"  # 132 / 100 - 1
    assert by_symbol["BETA"]["security_return_pct"] == "-5.00"  # 190 / 200 - 1
    # A price return and a contribution are different measurements and must not be conflated:
    # ALPHA rose 32% but contributed 13.18 points, because the contribution is weighed by the
    # portfolio's size on each session.
    assert by_symbol["ALPHA"]["contribution_pct"] == "13.18"
    assert Decimal(by_symbol["ALPHA"]["security_return_pct"]) != Decimal(by_symbol["ALPHA"]["contribution_pct"])


def test_golden_risk_and_cash_flow(golden_portfolio: tuple[TestClient, str]) -> None:
    client, portfolio_id = golden_portfolio

    body = get(client, portfolio_id, "intelligence", benchmark="GOLDEN")

    risk, cash = body["risk"], body["cash_flow"]
    # Growth index: 100 -> 96.6667 -> 103.4667 -> 105.3049 -> 110.3386, rising at the end.
    assert risk["max_drawdown_pct"] == "-3.33"  # 96.6667 / 100 - 1, the Tuesday fall
    assert risk["current_drawdown_pct"] == "0.00"  # the window closes at its own peak
    assert risk["positive_sessions"] == 3 and risk["negative_sessions"] == 1
    assert risk["flat_sessions"] == 0
    assert risk["volatility_pct"] is None  # four returns, far short of the 20 required
    # ALPHA 15 x 132 = 1,980 of 2,740; BETA 4 x 190 = 760.
    assert risk["largest_position_symbol"] == "ALPHA"
    assert risk["largest_position_weight_pct"] == "72.26"

    assert cash["start_value"] == "3000.00" and cash["end_value"] == "2740.00"
    assert cash["value_change"] == "-260.00"
    assert cash["net_external_flow"] == "2506.00"
    assert cash["return_driven_change"] == "-2766.00"  # -260 - 2,506
    assert cash["contributions"] == "3640.00"  # 1,010 + 2,020 + 610
    assert cash["withdrawals"] == "1134.00"


def test_golden_pnl(golden_portfolio: tuple[TestClient, str]) -> None:
    """FIFO: the BETA sale closes six of the ten bought at 200, carrying 60% of its 20 fees."""
    client, portfolio_id = golden_portfolio

    body = get(client, portfolio_id, "pnl")

    by_symbol = {item["symbol"]: item for item in body["securities"]}
    beta = by_symbol["BETA"]
    assert beta["realised_pnl"] == "-78.00"  # proceeds 1,134 - cost (1,200 + 12)
    assert beta["cost_basis"] == "808.00"  # 4 x 200 + 8 of the fees
    assert beta["unrealised_pnl"] == "-48.00"  # 4 x 190 - 808
    alpha = by_symbol["ALPHA"]
    assert alpha["cost_basis"] == "1620.00"  # 1,000 + 10 + 605 + 5
    assert alpha["unrealised_pnl"] == "360.00"  # 15 x 132 - 1,620
    totals = body["totals"]
    assert totals["realised_pnl"] == "-78.00"
    assert totals["total_pnl"] == "234.00"  # -78 + 360 - 48
    assert totals["net_invested"] == "2506.00"  # 3,640 - 1,134
    assert totals["fees"] == "41.00"


def test_golden_coverage_and_staleness(golden_portfolio: tuple[TestClient, str]) -> None:
    client, portfolio_id = golden_portfolio

    quality = get(client, portfolio_id, "intelligence", benchmark="GOLDEN")["data_quality"]

    assert quality["coverage_status"] == "complete"
    assert quality["sessions_available"] == 5 and quality["sessions_expected"] == 5
    assert quality["sessions_behind_latest"] == 0
    assert quality["missing_session_count"] == 0
    assert quality["stale_securities"] == []
    assert quality["reconciliation_status"] == "matches"
    assert quality["benchmark_status"] == "available"
    assert quality["limitations"] == []


def test_golden_values_are_identical_across_every_view(golden_portfolio: tuple[TestClient, str]) -> None:
    """The cards must agree with each other, not merely each be self-consistent."""
    client, portfolio_id = golden_portfolio

    performance = get(client, portfolio_id, "performance", benchmark="GOLDEN")
    attribution = get(client, portfolio_id, "attribution", benchmark="GOLDEN")
    intelligence = get(client, portfolio_id, "intelligence", benchmark="GOLDEN")
    allocation = get(client, portfolio_id, "allocation")

    assert intelligence["returns"]["portfolio_return_pct"] == performance["summary"]["cumulative_return_pct"]
    assert intelligence["returns"]["sum_of_contributions_pct"] == attribution["sum_of_daily_returns_pct"]
    assert intelligence["returns"]["benchmark_return_pct"] == performance["benchmark"]["cumulative_return_pct"]
    assert intelligence["risk"]["max_drawdown_pct"] == performance["summary"]["max_drawdown_pct"]
    assert intelligence["period"] == performance["period"] == attribution["period"]
    assert (
        intelligence["risk"]["largest_position_weight_pct"] == allocation["concentration"]["top_1_pct"]
    )
