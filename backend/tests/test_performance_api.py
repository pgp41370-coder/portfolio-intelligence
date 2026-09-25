"""Historical performance API against PostgreSQL with seeded listings and prices."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.performance import benchmarks as registry
from app.portfolios.rules import Exchange
from test_valuation_api import MakeClient, SessionFactory, add_listing, add_price, create_portfolio, make_client  # noqa: F401

# Sessions used throughout: Mon 14 Sep to Fri 18 Sep 2026, with the default weekday calendar.
MON, TUE, WED, THU, FRI = (date(2026, 9, day) for day in (14, 15, 16, 17, 18))
AFTER_FRIDAY = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)  # 18:30 IST on Friday
FRONTEND_ORIGIN = "https://portfolio-intelligence-bice.vercel.app"


def performance(client: TestClient, portfolio_id: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"/api/v1/portfolios/{portfolio_id}/performance", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def seed(factory: SessionFactory, provider_id: str, name: str, symbol: str, prices: dict[date, str]) -> str:
    listing_id = add_listing(factory, provider_id, name, nse=symbol)
    for day, close in prices.items():
        add_price(factory, listing_id, day, close)
    return listing_id


# --- Core arithmetic through the whole stack -------------------------------------------


def test_single_holding_value_series_and_returns(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Reliance Industries", "RELIANCE", {MON: "100", TUE: "110", WED: "121"})
    client = make_client(now=datetime(2026, 9, 16, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))

    body = performance(client, portfolio_id)

    assert [point["trade_date"] for point in body["series"]] == ["2026-09-14", "2026-09-15", "2026-09-16"]
    assert [point["value"] for point in body["series"]] == ["1000.00", "1100.00", "1210.00"]
    assert [point["daily_return_pct"] for point in body["series"]] == [None, "10.00", "10.00"]
    assert body["series"][-1]["cumulative_return_pct"] == "21.00"
    assert body["summary"]["start_value"] == "1000.00" and body["summary"]["end_value"] == "1210.00"
    assert body["summary"]["cumulative_return_pct"] == "21.00"
    assert body["summary"]["max_drawdown_pct"] == "0.00"
    assert body["summary"]["returns_used"] == 2
    assert body["coverage"]["status"] == "complete"
    assert body["coverage"]["sessions_expected"] == 3 and body["coverage"]["sessions_available"] == 3
    assert body["basis"] == "CURRENT_HOLDINGS"
    assert body["currency"] == "INR"


def test_five_holdings_are_summed_per_session(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    for index, symbol in enumerate(("RELIANCE", "TCS", "INFY", "HDFCBANK", "M&M"), start=1):
        seed(db_session_factory, f"S{index}", symbol.title(), symbol, {MON: "100", TUE: "200"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(
        client, *(("NSE", symbol, 2, "50") for symbol in ("RELIANCE", "TCS", "INFY", "HDFCBANK", "M&M"))
    )

    body = performance(client, portfolio_id)

    assert body["series"][0]["value"] == "1000.00"  # 5 holdings x 2 shares x 100
    assert body["series"][1]["value"] == "2000.00"
    assert body["summary"]["cumulative_return_pct"] == "100.00"
    assert body["excluded_holdings"] == []


def test_max_drawdown_is_reported(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "120", WED: "90", THU: "150"})
    client = make_client(now=datetime(2026, 9, 17, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))

    body = performance(client, portfolio_id)

    assert body["summary"]["max_drawdown_pct"] == "-25.00"  # 90 from a peak of 120


# --- Missing data is reported, never invented ------------------------------------------


def test_session_missing_one_price_is_excluded_not_partially_valued(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "120"})
    seed(db_session_factory, "S2", "TCS", "TCS", {MON: "200", WED: "240"})  # no Tuesday close
    client = make_client(now=datetime(2026, 9, 16, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"), ("NSE", "TCS", 1, "200"))

    body = performance(client, portfolio_id)

    assert [point["trade_date"] for point in body["series"]] == ["2026-09-14", "2026-09-16"]
    assert [point["value"] for point in body["series"]] == ["300.00", "360.00"]  # Tuesday never valued at 110
    assert body["coverage"]["status"] == "partial"
    assert body["coverage"]["missing_sessions"] == ["2026-09-15"]
    assert body["coverage"]["missing_session_count"] == 1
    assert body["coverage"]["missing_some_prices_count"] == 1  # Reliance was priced, TCS was not
    assert body["coverage"]["missing_no_prices_at_all_count"] == 0
    assert body["summary"]["returns_used"] == 0  # the only pair spans the gap
    assert body["summary"]["returns_skipped_across_gaps"] == 1
    assert body["series"][-1]["daily_return_pct"] is None
    assert body["summary"]["cumulative_return_pct"] == "20.00"  # endpoints remain valid
    assert "not linked across" in body["coverage"]["note"]
    assert "only some holdings" in body["coverage"]["note"]


def test_session_with_no_prices_at_all_is_reported_separately(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """A day no holding was priced is usually a market closure the calendar does not list.

    It is still reported as missing - the alternative reading is a sync that failed for every
    security, and the two cannot be told apart from stored prices alone.
    """
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", WED: "120"})
    seed(db_session_factory, "S2", "TCS", "TCS", {MON: "200", WED: "240"})  # neither has Tuesday
    client = make_client(now=datetime(2026, 9, 16, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"), ("NSE", "TCS", 1, "200"))

    body = performance(client, portfolio_id)

    assert body["coverage"]["status"] == "partial"
    assert body["coverage"]["missing_sessions"] == ["2026-09-15"]
    assert body["coverage"]["missing_no_prices_at_all_count"] == 1
    assert body["coverage"]["missing_some_prices_count"] == 0
    assert "no price for any holding" in body["coverage"]["note"]
    assert "exchange holiday" in body["coverage"]["note"]
    assert body["summary"]["returns_used"] == 0  # still never linked across the gap
    assert body["summary"]["returns_skipped_across_gaps"] == 1


def test_holdings_without_usable_prices_are_excluded_with_reasons(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    add_listing(db_session_factory, "S2", "TCS", nse="TCS")  # listed but never priced
    add_listing(db_session_factory, "S3", "UR Sugar", bse="539097")  # BSE only
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(
        client,
        ("NSE", "RELIANCE", 1, "100"),
        ("NSE", "TCS", 1, "100"),
        ("BSE", "539097", 1, "10"),
        ("NSE", "UNKNOWNCO", 1, "10"),
    )

    body = performance(client, portfolio_id)

    reasons = {item["symbol"]: item["reason"] for item in body["excluded_holdings"]}
    assert reasons == {"TCS": "NO_PRICE_DATA", "539097": "NO_NSE_LISTING", "UNKNOWNCO": "LISTING_NOT_FOUND"}
    assert [point["value"] for point in body["series"]] == ["100.00", "110.00"]  # priced holding only


def test_portfolio_without_any_priced_holding_is_insufficient(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    client = make_client(now=AFTER_FRIDAY)
    portfolio_id = create_portfolio(client, ("NSE", "UNKNOWNCO", 1, "10"))

    body = performance(client, portfolio_id)

    assert body["coverage"]["status"] == "insufficient"
    assert body["series"] == []
    assert body["summary"]["cumulative_return_pct"] is None
    assert body["summary"]["start_value"] is None
    assert "no holding" in body["coverage"]["note"].lower()


def test_one_session_is_insufficient_for_a_return(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100"})
    client = make_client(now=datetime(2026, 9, 14, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))

    body = performance(client, portfolio_id)

    assert body["coverage"]["status"] == "insufficient"
    assert body["summary"]["cumulative_return_pct"] is None
    assert body["summary"]["max_drawdown_pct"] is None
    assert len(body["series"]) == 1


def test_volatility_is_withheld_until_enough_observations(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "121"})
    client = make_client(now=datetime(2026, 9, 16, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))

    body = performance(client, portfolio_id)

    assert body["summary"]["volatility_pct"] is None
    assert "at least 20 daily returns" in body["summary"]["volatility_note"]


def test_volatility_is_reported_with_a_full_window(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    prices = {}
    day = date(2026, 8, 3)  # a Monday
    close = 100
    while len(prices) < 25:
        if day.weekday() < 5:
            close = close + 2 if len(prices) % 2 else close - 2
            prices[day] = str(close)
        day = date.fromordinal(day.toordinal() + 1)
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", prices)
    client = make_client(now=AFTER_FRIDAY)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))

    body = performance(client, portfolio_id)

    assert body["summary"]["returns_used"] >= 20
    assert body["summary"]["volatility_pct"] is not None
    assert Decimal(body["summary"]["volatility_pct"]) > 0
    assert body["summary"]["volatility_note"] is None
    assert body["methodology"]["trading_days_per_year"] == 252


# --- Window, benchmark, isolation, errors ----------------------------------------------


def test_window_parameters_narrow_the_series(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "120", THU: "130"})
    client = make_client(now=datetime(2026, 9, 17, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))

    body = performance(client, portfolio_id, start_date="2026-09-15", end_date="2026-09-16")

    assert [point["trade_date"] for point in body["series"]] == ["2026-09-15", "2026-09-16"]
    assert body["period"] == {"start": "2026-09-15", "end": "2026-09-16"}
    assert body["summary"]["cumulative_return_pct"] == "9.09"


def test_start_after_end_is_rejected(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    client = make_client(now=AFTER_FRIDAY)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))

    response = client.get(
        f"/api/v1/portfolios/{portfolio_id}/performance",
        params={"start_date": "2026-09-18", "end_date": "2026-09-14"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_date_range"


def test_benchmark_is_never_fabricated(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))

    without = performance(client, portfolio_id)
    requested = performance(client, portfolio_id, benchmark="NIFTY50")
    unknown = performance(client, portfolio_id, benchmark="SENSEX")

    assert without["benchmark"]["status"] == "not_requested"
    # NIFTY50 is registered as an ETF proxy, but its prices have not been synced in this
    # database: the answer is "no data", never an invented series.
    assert requested["benchmark"]["status"] == "no_data"
    assert requested["benchmark"]["cumulative_return_pct"] is None
    assert requested["benchmark"]["series"] == []
    assert "not been synced" in requested["benchmark"]["note"]
    assert unknown["benchmark"]["status"] == "unknown_key"
    assert unknown["benchmark"]["cumulative_return_pct"] is None

    listed = client.get("/api/v1/benchmarks").json()
    assert [item["key"] for item in listed] == ["NIFTY50"]
    assert listed[0]["is_proxy"] is True and listed[0]["tracks"] == "NIFTY 50"


def test_benchmark_comparison_works_when_a_series_exists(
    make_client: MakeClient, db_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    seed(db_session_factory, "S2", "Index ETF", "SETFNIF50", {MON: "200", TUE: "210"})
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
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))

    body = performance(client, portfolio_id, benchmark="testbm")

    assert body["benchmark"]["status"] == "available"
    assert body["benchmark"]["display_name"] == "Test index ETF"
    assert body["benchmark"]["cumulative_return_pct"] == "5.00"  # 210 / 200 - 1
    assert body["benchmark"]["excess_return_pct"] == "5.00"  # 10.00 - 5.00
    assert body["benchmark"]["sessions_compared"] == 2
    # The series is rebased to 100 at the first shared session, so it is comparable on a chart.
    assert body["benchmark"]["series"] == [
        {"trade_date": "2026-09-14", "index": "100.00"},
        {"trade_date": "2026-09-15", "index": "105.00"},
    ]
    # An ETF standing in for an index says so rather than posing as the index.
    assert body["benchmark"]["is_proxy"] is True and body["benchmark"]["basis"] == "ETF_PROXY"
    assert {item["key"] for item in client.get("/api/v1/benchmarks").json()} == {"NIFTY50", "TESTBM"}


def test_portfolios_are_isolated(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    seed(db_session_factory, "S2", "TCS", "TCS", {MON: "100", TUE: "90"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    first = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))
    second = create_portfolio(client, ("NSE", "TCS", 1, "100"))

    assert performance(client, first)["summary"]["cumulative_return_pct"] == "10.00"
    assert performance(client, second)["summary"]["cumulative_return_pct"] == "-10.00"


def test_unknown_portfolio_returns_404(make_client: MakeClient) -> None:
    client = make_client(now=AFTER_FRIDAY)

    response = client.get("/api/v1/portfolios/00000000-0000-0000-0000-000000000000/performance")

    assert response.status_code == 404


def test_performance_is_readable_in_production_and_writes_stay_blocked(migrated_database_url: str) -> None:
    production = Settings(
        _env_file=None,
        app_env="production",
        database_url=migrated_database_url,
        cors_allowed_origins=[FRONTEND_ORIGIN],
        nse_trading_holidays=[],
        nse_special_trading_sessions=[],
    )
    with TestClient(create_app(production)) as client:
        read = client.get("/api/v1/portfolios/00000000-0000-0000-0000-000000000000/performance")
        write = client.post("/api/v1/portfolios", json={"name": "blocked", "holdings": []})

    assert read.status_code == 404  # reached the route, portfolio simply does not exist
    assert write.status_code == 403


def test_performance_never_calls_the_market_data_provider(
    make_client: MakeClient, db_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.market_data.providers.indian_api import IndianApiProvider

    def explode(*_: object, **__: object) -> None:
        raise AssertionError("performance must read stored prices only")

    monkeypatch.setattr(IndianApiProvider, "_request_json", explode)
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 1, "100"))

    assert performance(client, portfolio_id)["summary"]["cumulative_return_pct"] == "10.00"
