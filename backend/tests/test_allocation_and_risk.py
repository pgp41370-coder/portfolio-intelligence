"""Allocation, concentration and risk analytics."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.performance import benchmarks as registry
from app.performance import risk
from app.performance.allocation import PositionValue, concentration, weights
from app.portfolios.rules import Exchange
from test_performance_api import MakeClient, SessionFactory, performance, seed  # noqa: F401
from test_valuation_api import add_listing, add_price, create_portfolio, make_client  # noqa: F401

MON, TUE = date(2026, 9, 14), date(2026, 9, 15)
TUESDAY_EVENING = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


def allocation(client: TestClient, portfolio_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/portfolios/{portfolio_id}/allocation")
    assert response.status_code == 200, response.text
    return response.json()


def position(symbol: str, value: str) -> PositionValue:
    return PositionValue(symbol=symbol, exchange="NSE", value=Decimal(value))


# --- Weights and concentration arithmetic (no database) ---------------------------------


def test_weights_are_shares_of_the_priced_total() -> None:
    ranked = weights([position("A", "5000"), position("B", "3000"), position("C", "2000")])

    assert [item.symbol for item in ranked] == ["A", "B", "C"]  # largest first
    assert [str(item.weight) for item in ranked] == ["0.5", "0.3", "0.2"]


def test_positions_worth_nothing_are_not_weighted() -> None:
    assert weights([position("A", "0")]) == []
    assert weights([]) == []


def test_concentration_measures_the_largest_positions() -> None:
    ranked = weights([position(name, value) for name, value in
                      (("A", "5000"), ("B", "2000"), ("C", "1500"), ("D", "1000"), ("E", "500"))])

    measured = concentration(ranked)

    assert measured.holdings_counted == 5
    assert measured.top_weight.symbol == "A"
    assert measured.top_1_pct == Decimal(50)
    assert measured.top_3_pct == Decimal(85)  # 50 + 20 + 15
    assert measured.top_5_pct == Decimal(100)
    # HHI on the 0-10,000 scale: 50^2 + 20^2 + 15^2 + 10^2 + 5^2.
    assert measured.hhi == Decimal(3250)
    assert measured.hhi_band == "highly concentrated"


def test_concentration_bands_follow_the_standard_thresholds() -> None:
    # Ten equal positions: HHI 1,000.
    even = concentration(weights([position(f"S{index}", "100") for index in range(10)]))
    assert even.hhi == Decimal(1000) and even.hhi_band == "diversified"
    assert even.effective_holdings == Decimal(10)

    single = concentration(weights([position("ONLY", "100")]))
    assert single.hhi == Decimal(10_000) and single.hhi_band == "highly concentrated"
    assert single.effective_holdings == Decimal(1)


def test_concentration_of_an_empty_portfolio_is_empty_not_zero() -> None:
    measured = concentration([])

    assert measured.holdings_counted == 0
    assert measured.top_weight is None
    assert measured.hhi is None and measured.hhi_band is None


# --- Allocation through the API ------------------------------------------------------------


def test_allocation_weights_match_the_valuation(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {TUE: "100"})
    seed(db_session_factory, "S2", "TCS", "TCS", {TUE: "300"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "50"), ("NSE", "TCS", 10, "50"))

    body = allocation(client, portfolio_id)
    valuation = client.get(f"/api/v1/portfolios/{portfolio_id}/valuation").json()

    assert body["priced_market_value"] == valuation["totals"]["total_market_value"] == "4000.00"
    assert [(item["symbol"], item["weight_pct"]) for item in body["holdings"]] == [
        ("TCS", "75.00"),
        ("RELIANCE", "25.00"),
    ]
    assert body["concentration"]["top_holding"]["symbol"] == "TCS"
    assert body["concentration"]["top_1_pct"] == "75.00"
    assert body["concentration"]["hhi"] == "6250.00"  # 75^2 + 25^2
    assert body["concentration"]["hhi_band"] == "highly concentrated"


def test_unpriced_holdings_are_listed_not_weighted_as_zero(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {TUE: "100"})
    add_listing(db_session_factory, "S2", "TCS", nse="TCS")  # listed, never priced
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "50"), ("NSE", "TCS", 99, "50"))

    body = allocation(client, portfolio_id)

    assert [item["symbol"] for item in body["holdings"]] == ["RELIANCE"]
    assert body["holdings"][0]["weight_pct"] == "100.00"  # of the priced value
    assert body["unpriced_positions"] == [
        {"symbol": "TCS", "exchange": "NSE", "quantity": 99, "reason": "NO_PRICE_DATA"}
    ]
    assert "given no weight" in body["note"]


def test_sector_allocation_is_reported_unavailable_not_invented(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance Industries", "RELIANCE", {TUE: "100"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "50"))

    body = allocation(client, portfolio_id)

    assert body["sectors"]["available"] is False
    assert body["sectors"]["weights"] == []
    assert "no sector or industry classification" in body["sectors"]["note"]


def test_allocation_of_an_empty_portfolio_is_honest(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client)

    body = allocation(client, portfolio_id)

    assert body["holdings"] == []
    assert body["concentration"]["holdings_counted"] == 0
    assert body["concentration"]["hhi"] is None


def test_allocation_requires_a_known_portfolio(make_client: MakeClient) -> None:
    client = make_client(now=TUESDAY_EVENING)

    response = client.get("/api/v1/portfolios/00000000-0000-0000-0000-000000000000/allocation")

    assert response.status_code == 404


# --- Risk measures (no database) --------------------------------------------------------------


def test_downside_volatility_needs_enough_losing_days() -> None:
    mostly_flat = [Decimal("0.001")] * 25

    measure = risk.downside_volatility(mostly_flat)

    assert not measure.available
    assert "below the threshold" in measure.note


def test_downside_volatility_ignores_gains() -> None:
    returns = [Decimal("-0.02")] * 10 + [Decimal("0.05")] * 15

    measure = risk.downside_volatility(returns)

    assert measure.available
    # sqrt(10 x 0.02^2 / 25) x sqrt(252) = 0.01264911... x 15.8745 ~= 0.2008
    assert Decimal("0.19") < measure.value < Decimal("0.21")


def test_beta_and_tracking_error_need_paired_observations() -> None:
    short = [Decimal("0.01")] * 5

    assert not risk.beta(short, short).available
    assert "paired daily returns" in risk.beta(short, short).note
    assert not risk.tracking_error(short, short).available


def test_beta_of_a_portfolio_that_moves_with_the_benchmark_is_one() -> None:
    benchmark = [Decimal(str(value)) for value in ([0.01, -0.02, 0.015, -0.005] * 6)]

    measure = risk.beta(benchmark, benchmark)

    assert measure.available and measure.value == Decimal(1)
    assert risk.tracking_error(benchmark, benchmark).value == Decimal(0)


def test_beta_of_a_doubly_geared_portfolio_is_two() -> None:
    benchmark = [Decimal(str(value)) for value in ([0.01, -0.02, 0.015, -0.005] * 6)]
    portfolio = [value * 2 for value in benchmark]

    assert risk.beta(portfolio, benchmark).value == Decimal(2)


def test_paired_returns_drop_days_either_series_missed() -> None:
    portfolio = [Decimal("0.01"), None, Decimal("0.02"), Decimal("0.03")]
    benchmark = [Decimal("0.01"), Decimal("0.01"), None, Decimal("0.02")]

    paired_p, paired_b = risk.paired_returns(portfolio, benchmark)

    assert paired_p == [Decimal("0.01"), Decimal("0.03")]
    assert paired_b == [Decimal("0.01"), Decimal("0.02")]


def test_beta_is_undefined_when_the_benchmark_never_moves() -> None:
    flat = [Decimal(0)] * 25
    portfolio = [Decimal("0.01")] * 25

    measure = risk.beta(portfolio, flat)

    assert not measure.available and "did not move" in measure.note


def test_sharpe_is_withheld_without_a_configured_risk_free_rate() -> None:
    measure = risk.sharpe_ratio(Decimal("0.12"), Decimal("0.18"), risk_free_rate=None)

    assert not measure.available
    assert "RISK_FREE_RATE_PCT" in measure.note


def test_sharpe_is_computed_when_a_rate_is_configured() -> None:
    measure = risk.sharpe_ratio(
        Decimal("0.12"), Decimal("0.18"), risk_free_rate=Decimal("0.06"), years=Decimal(1)
    )

    assert measure.available
    # (0.12 - 0.06) / 0.18 = 0.3333..., compared at a sane precision rather than 34 digits.
    assert measure.value.quantize(Decimal("0.000001")) == Decimal("0.333333")


def test_information_ratio_needs_a_tracking_error() -> None:
    unavailable = risk.Measure(None, "not enough data")

    measure = risk.information_ratio(Decimal("0.05"), unavailable)

    assert not measure.available and measure.note == "not enough data"


# --- Risk through the API ----------------------------------------------------------------------


def test_risk_block_withholds_what_it_cannot_measure(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))

    body = performance(client, portfolio_id)

    assert body["risk"]["observations"] == 1
    assert body["risk"]["volatility_pct"] is None
    for measure in ("downside_volatility", "beta", "tracking_error_pct", "information_ratio", "sharpe_ratio"):
        assert body["risk"][measure]["available"] is False, measure
        assert body["risk"][measure]["note"], measure
    assert "RISK_FREE_RATE_PCT" in body["risk"]["sharpe_ratio"]["note"]


def test_sharpe_appears_once_a_risk_free_rate_is_configured(
    db_session_factory: SessionFactory, migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings
    from app.main import create_app

    days = [date(2026, 7, 1) + __import__("datetime").timedelta(days=offset) for offset in range(75)]
    sessions = [day for day in days if day.weekday() < 5 and day != date(2026, 9, 14)]
    listing_id = add_listing(db_session_factory, "S1", "Reliance", nse="RELIANCE")
    for index, day in enumerate(sessions):
        add_price(db_session_factory, listing_id, day, str(100 + index))

    settings = Settings(
        _env_file=None, app_env="test", database_url=migrated_database_url, risk_free_rate_pct=Decimal("6.5")
    )
    # A window ending after the last seeded session, so every one of them is in range.
    with TestClient(create_app(settings)) as client:
        portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))
        body = client.get(f"/api/v1/portfolios/{portfolio_id}/performance").json()

    assert body["risk"]["observations"] >= 20
    assert body["risk"]["volatility_pct"] is not None
    assert body["risk"]["sharpe_ratio"]["available"] is True
    assert body["risk"]["sharpe_ratio"]["value"] is not None


def test_benchmark_risk_measures_appear_with_a_comparable_series(
    make_client: MakeClient, db_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    import datetime as dt

    days = [date(2026, 9, 1) + dt.timedelta(days=offset) for offset in range(40)]
    sessions = [day for day in days if day.weekday() < 5 and day != date(2026, 9, 14)]
    portfolio_listing = add_listing(db_session_factory, "S1", "Reliance", nse="RELIANCE")
    benchmark_listing = add_listing(db_session_factory, "S2", "Index ETF", nse="SETFNIF50")
    for index, day in enumerate(sessions):
        add_price(db_session_factory, portfolio_listing, day, str(Decimal(100) + Decimal(index) * 2))
        add_price(db_session_factory, benchmark_listing, day, str(Decimal(200) + Decimal(index) * 2))

    monkeypatch.setitem(
        registry.BENCHMARKS,
        "TESTBM",
        registry.BenchmarkDefinition(
            key="TESTBM",
            display_name="Test index ETF",
            nse_symbol="SETFNIF50",
            exchange=Exchange.NSE,
            tracks="Test index",
            source="test fixture",
            is_proxy=True,
            methodology="Daily closes rebased to 100.",
            note="ETF proxy, not the index itself.",
        ),
    )
    client = make_client(now=datetime(2026, 10, 9, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))

    body = performance(client, portfolio_id, benchmark="TESTBM")

    assert body["benchmark"]["status"] == "available"
    assert len(body["benchmark"]["series"]) == body["benchmark"]["sessions_compared"]
    assert body["risk"]["beta"]["available"] is True
    assert body["risk"]["tracking_error_pct"]["available"] is True
    assert body["risk"]["information_ratio"]["available"] is True
