"""Transaction-aware performance: the ledger, the position engine and time-weighted return.

The twelve scenarios the M4.2 brief requires are all here, end to end through the API against
PostgreSQL, plus the ledger validation rules.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from test_performance_api import MakeClient, SessionFactory, performance, seed  # noqa: F401
from test_valuation_api import add_listing, add_price, create_portfolio, make_client  # noqa: F401

# Mon 14 Sep to Fri 18 Sep 2026 are consecutive sessions under the default weekday calendar.
MON, TUE, WED, THU, FRI = (date(2026, 9, day) for day in (14, 15, 16, 17, 18))
SATURDAY, SUNDAY = date(2026, 9, 12), date(2026, 9, 13)
AFTER_FRIDAY = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)  # 18:30 IST


def add_transactions(client: TestClient, portfolio_id: str, *rows: dict[str, Any]) -> list[dict[str, Any]]:
    response = client.post(f"/api/v1/portfolios/{portfolio_id}/transactions", json=list(rows))
    assert response.status_code == 201, response.text
    return response.json()


def buy(symbol: str, day: date, quantity: int, price: str, **extra: Any) -> dict[str, Any]:
    return {"symbol": symbol, "exchange": "NSE", "kind": "BUY", "trade_date": day.isoformat(),
            "quantity": quantity, "price": price, **extra}


def sell(symbol: str, day: date, quantity: int, price: str, **extra: Any) -> dict[str, Any]:
    return {"symbol": symbol, "exchange": "NSE", "kind": "SELL", "trade_date": day.isoformat(),
            "quantity": quantity, "price": price, **extra}


# --- 1. Single buy ----------------------------------------------------------------------


def test_single_buy_uses_the_transaction_basis(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "121"})
    client = make_client(now=datetime(2026, 9, 16, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = performance(client, portfolio_id)

    assert body["basis"] == "TRANSACTIONS"
    assert body["methodology"]["calculation_method"] == "TWR_DAILY_CHAINED"
    assert [point["value"] for point in body["series"]] == ["1000.00", "1100.00", "1210.00"]
    # The opening buy is a contribution, so Monday itself earns no return.
    assert [point["daily_return_pct"] for point in body["series"]] == [None, "10.00", "10.00"]
    assert body["summary"]["cumulative_return_pct"] == "21.00"  # 1.10 x 1.10 - 1
    assert body["summary"]["returns_skipped_zero_base"] == 0  # the first session has no predecessor
    assert body["summary"]["net_external_flow"] == "1000.00"
    assert body["reconciliation"]["status"] == "matches"


# --- 2. Multiple buys -------------------------------------------------------------------


def test_second_buy_is_a_contribution_not_a_gain(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """The classic error this guards against: value doubling because money was added."""
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "100", WED: "110"})
    client = make_client(now=datetime(2026, 9, 16, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 20, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), buy("RELIANCE", TUE, 10, "100"))

    body = performance(client, portfolio_id)

    assert [point["value"] for point in body["series"]] == ["1000.00", "2000.00", "2200.00"]
    # Tuesday's value doubled purely because 1,000 was added: the return is zero, not 100%.
    assert [point["daily_return_pct"] for point in body["series"]] == [None, "0.00", "10.00"]
    assert body["summary"]["cumulative_return_pct"] == "10.00"
    assert body["summary"]["net_external_flow"] == "2000.00"


# --- 3. Buy then sell, and 4. partial sell ----------------------------------------------


def test_full_sell_leaves_an_empty_portfolio(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "120"})
    client = make_client(now=datetime(2026, 9, 16, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client)
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), sell("RELIANCE", TUE, 10, "110"))

    body = performance(client, portfolio_id)

    assert [point["value"] for point in body["series"]] == ["1000.00", "0.00", "0.00"]
    # Selling at Tuesday's close is a withdrawal, so the 10% gain still shows as the return.
    assert body["series"][1]["daily_return_pct"] == "10.00"
    assert body["summary"]["cumulative_return_pct"] == "10.00"
    assert body["summary"]["net_external_flow"] == "-100.00"  # 1,000 in, 1,100 out
    assert body["reconciliation"]["status"] == "matches"  # no holdings, no open position


def test_partial_sell_keeps_the_remaining_position(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "121"})
    client = make_client(now=datetime(2026, 9, 16, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 4, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), sell("RELIANCE", TUE, 6, "110"))

    body = performance(client, portfolio_id)

    assert [point["value"] for point in body["series"]] == ["1000.00", "440.00", "484.00"]
    assert [point["daily_return_pct"] for point in body["series"]] == [None, "10.00", "10.00"]
    assert body["summary"]["cumulative_return_pct"] == "21.00"  # unaffected by the withdrawal


# --- 5-7. Flat, rising and falling markets ----------------------------------------------


def test_flat_market_returns_zero(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "100", WED: "100"})
    client = make_client(now=datetime(2026, 9, 16, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = performance(client, portfolio_id)

    assert body["summary"]["cumulative_return_pct"] == "0.00"
    assert body["summary"]["max_drawdown_pct"] == "0.00"


def test_rising_and_falling_markets(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Up", "UPCO", {MON: "100", TUE: "150"})
    seed(db_session_factory, "S2", "Down", "DOWNCO", {MON: "100", TUE: "50"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))

    rising = create_portfolio(client, ("NSE", "UPCO", 10, "100"))
    add_transactions(client, rising, buy("UPCO", MON, 10, "100"))
    assert performance(client, rising)["summary"]["cumulative_return_pct"] == "50.00"

    falling = create_portfolio(client, ("NSE", "DOWNCO", 10, "100"))
    add_transactions(client, falling, buy("DOWNCO", MON, 10, "100"))
    body = performance(client, falling)
    assert body["summary"]["cumulative_return_pct"] == "-50.00"
    assert body["summary"]["max_drawdown_pct"] == "-50.00"


# --- 8. Transaction on a non-trading day -------------------------------------------------


def test_weekend_trade_date_is_recognised_at_the_next_session(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", SUNDAY, 10, "100"))

    body = performance(client, portfolio_id)

    assert body["period"]["start"] == "2026-09-14"  # Monday, the first session on or after
    assert [point["value"] for point in body["series"]] == ["1000.00", "1100.00"]
    assert "not trading sessions" in body["coverage"]["note"]
    assert "13 Sep 2026" in body["coverage"]["note"]


# --- 9. Multiple transactions on the same day --------------------------------------------


def test_same_day_transactions_are_netted(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 15, "100"))
    add_transactions(
        client,
        portfolio_id,
        buy("RELIANCE", MON, 10, "100"),
        buy("RELIANCE", MON, 10, "102"),
        sell("RELIANCE", MON, 5, "104"),
    )

    body = performance(client, portfolio_id)

    assert body["series"][0]["value"] == "1500.00"  # 15 shares at Monday's close
    # 1,000 + 1,020 paid, 520 received.
    assert body["summary"]["net_external_flow"] == "1500.00"
    assert body["reconciliation"]["status"] == "matches"


# --- 10. Missing market data --------------------------------------------------------------


def test_missing_close_is_reported_not_invented(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", WED: "121"})  # no Tuesday
    client = make_client(now=datetime(2026, 9, 16, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = performance(client, portfolio_id)

    assert [point["trade_date"] for point in body["series"]] == ["2026-09-14", "2026-09-16"]
    assert body["coverage"]["status"] == "partial"
    assert body["coverage"]["missing_sessions"] == ["2026-09-15"]
    assert body["series"][-1]["daily_return_pct"] is None  # never linked across the gap
    assert body["summary"]["returns_used"] == 0
    assert body["summary"]["returns_skipped_across_gaps"] == 1
    assert body["summary"]["cumulative_return_pct"] is None  # no measurable return at all


def test_security_with_no_prices_is_excluded_with_a_reason(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    add_listing(db_session_factory, "S2", "TCS", nse="TCS")  # listed but never priced
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "TCS", 10, "100"))
    add_transactions(client, portfolio_id, buy("TCS", MON, 10, "100"))

    body = performance(client, portfolio_id)

    assert body["coverage"]["status"] in {"insufficient", "partial"}
    assert body["series"] == [] or all(point["value"] == "0.00" for point in body["series"])
    assert body["summary"]["cumulative_return_pct"] is None


# --- 11. Zero-position periods --------------------------------------------------------------


def test_zero_position_period_carries_no_return(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """Out of the market on Wednesday, back in on Thursday: the gap earns nothing and loses nothing."""
    seed(db_session_factory, "S1", "Reliance", "RELIANCE",
         {MON: "100", TUE: "110", WED: "50", THU: "200", FRI: "220"})
    client = make_client(now=AFTER_FRIDAY)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(
        client,
        portfolio_id,
        buy("RELIANCE", MON, 10, "100"),
        sell("RELIANCE", TUE, 10, "110"),  # out of the market before the crash
        buy("RELIANCE", THU, 10, "200"),
    )

    body = performance(client, portfolio_id)

    # Tuesday's sale is recognised at that day's close, so nothing is held at the close.
    assert [point["value"] for point in body["series"]] == ["1000.00", "0.00", "0.00", "2000.00", "2200.00"]
    assert [point["daily_return_pct"] for point in body["series"]] == [None, "10.00", None, None, "10.00"]
    # Wednesday's 55% price fall is not the portfolio's loss - it held nothing.
    assert body["summary"]["cumulative_return_pct"] == "21.00"  # 1.10 x 1.00 x 1.10 - 1
    assert body["summary"]["returns_skipped_zero_base"] == 2  # the first session and Thursday
    assert body["summary"]["max_drawdown_pct"] == "0.00"


# --- 12. External cash flow ------------------------------------------------------------------


def test_large_contribution_does_not_inflate_the_return(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "100", WED: "90"})
    client = make_client(now=datetime(2026, 9, 16, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 110, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), buy("RELIANCE", TUE, 100, "100"))

    body = performance(client, portfolio_id)

    assert [point["value"] for point in body["series"]] == ["1000.00", "11000.00", "9900.00"]
    assert [point["daily_return_pct"] for point in body["series"]] == [None, "0.00", "-10.00"]
    assert body["summary"]["cumulative_return_pct"] == "-10.00"


def test_execution_price_away_from_the_close_is_a_real_gain(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """Buying 10 below the close is a gain that day; the flow is what was actually paid."""
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "100"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 20, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), buy("RELIANCE", TUE, 10, "90"))

    body = performance(client, portfolio_id)

    # Tuesday: value 2,000, flow 900 -> (2000 - 900) / 1000 - 1 = 10%.
    assert body["series"][1]["daily_return_pct"] == "10.00"


def test_fees_reduce_the_return(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "100"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 20, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), buy("RELIANCE", TUE, 10, "100", fees="50"))

    body = performance(client, portfolio_id)

    # Value 2,000, flow 1,050 -> (2000 - 1050) / 1000 - 1 = -5%.
    assert body["series"][1]["daily_return_pct"] == "-5.00"
    assert body["summary"]["net_external_flow"] == "2050.00"


# --- Ledger validation -------------------------------------------------------------------------


def test_selling_more_than_held_is_rejected(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client)
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    response = client.post(
        f"/api/v1/portfolios/{portfolio_id}/transactions", json=[sell("RELIANCE", TUE, 11, "110")]
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "oversold_position"
    assert client.get(f"/api/v1/portfolios/{portfolio_id}/transactions").json()["count"] == 1


def test_future_trade_date_is_rejected(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))  # latest session: Tue 15 Sep
    portfolio_id = create_portfolio(client)

    response = client.post(
        f"/api/v1/portfolios/{portfolio_id}/transactions", json=[buy("RELIANCE", date(2026, 9, 17), 1, "100")]
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "future_trade_date"


def test_deleting_a_transaction_that_would_oversell_is_refused(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client)
    created = add_transactions(
        client, portfolio_id, buy("RELIANCE", MON, 10, "100"), sell("RELIANCE", TUE, 10, "110")
    )

    refused = client.delete(f"/api/v1/portfolios/{portfolio_id}/transactions/{created[0]['id']}")
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "oversold_position"

    allowed = client.delete(f"/api/v1/portfolios/{portfolio_id}/transactions/{created[1]['id']}")
    assert allowed.status_code == 204


def test_ledger_round_trips_through_the_api(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client)
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "1234.5", fees="23.6", reference="ORD-1"))

    body = client.get(f"/api/v1/portfolios/{portfolio_id}/transactions").json()

    assert body["count"] == 1
    row = body["transactions"][0]
    assert row["symbol"] == "RELIANCE" and row["kind"] == "BUY"
    assert row["price"] == "1234.50" and row["fees"] == "23.60" and row["reference"] == "ORD-1"


# --- Reconciliation ------------------------------------------------------------------------------


def test_ledger_disagreeing_with_holdings_is_reported_not_resolved(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 25, "100"))  # user says 25
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))  # ledger says 10

    body = performance(client, portfolio_id)

    assert body["reconciliation"]["status"] == "differs"
    assert body["reconciliation"]["differences"] == [
        {"symbol": "RELIANCE", "exchange": "NSE", "ledger_quantity": 10, "holdings_quantity": 25}
    ]
    # The series follows the ledger; valuation still follows the holdings.
    assert body["series"][0]["value"] == "1000.00"
    valuation = client.get(f"/api/v1/portfolios/{portfolio_id}/valuation").json()
    assert valuation["totals"]["total_market_value"] == "2750.00"


# --- The M4.1 basis is untouched ------------------------------------------------------------------


def test_portfolio_without_transactions_keeps_the_reconstruction_basis(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))

    body = performance(client, portfolio_id)

    assert body["basis"] == "CURRENT_HOLDINGS"
    assert body["methodology"]["calculation_method"] == "PRICE_RETURN_ENDPOINTS"
    assert body["reconciliation"]["status"] == "not_applicable"
    assert body["summary"]["net_external_flow"] is None


def test_transaction_endpoints_are_read_only_in_production(
    make_client: MakeClient, db_session_factory: SessionFactory, migrated_database_url: str
) -> None:
    from app.core.config import Settings
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url=migrated_database_url,
        cors_allowed_origins=["https://portfolio-intelligence-bice.vercel.app"],
    )
    with TestClient(create_app(settings)) as client:
        portfolio_id = "00000000-0000-0000-0000-000000000000"
        created = client.post(f"/api/v1/portfolios/{portfolio_id}/transactions", json=[buy("RELIANCE", MON, 1, "100")])
        deleted = client.delete(f"/api/v1/portfolios/{portfolio_id}/transactions/{portfolio_id}")

    assert created.status_code == 403 and created.json()["error"]["code"] == "read_only_demo"
    assert deleted.status_code == 403 and deleted.json()["error"]["code"] == "read_only_demo"


# --- Stale prices are named as staleness, not as missing sessions --------------------------


def test_stale_prices_end_the_window_and_are_reported(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """Prices that stop before the latest session must not read as a run of unpriced days."""
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    # "Now" is the following Friday evening, so Wed, Thu and Fri are completed sessions with
    # no stored close.
    client = make_client(now=AFTER_FRIDAY)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = performance(client, portfolio_id)

    assert body["period"]["end"] == "2026-09-15"  # the window stops at the data
    assert body["coverage"]["missing_session_count"] == 0  # not treated as gaps
    assert body["coverage"]["sessions_behind_latest"] == 3
    assert body["coverage"]["latest_expected_session"] == "2026-09-18"
    assert "behind the market" in body["coverage"]["note"]
    assert body["summary"]["cumulative_return_pct"] == "10.00"


def test_the_holdings_basis_reports_staleness_the_same_way(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=AFTER_FRIDAY)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))  # no ledger

    body = performance(client, portfolio_id)

    assert body["basis"] == "CURRENT_HOLDINGS"
    assert body["coverage"]["sessions_behind_latest"] == 3
    assert "behind the market" in body["coverage"]["note"]


def test_current_prices_report_no_lag(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))  # Tuesday evening

    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    body = performance(client, portfolio_id)

    assert body["coverage"]["sessions_behind_latest"] == 0
    assert body["coverage"]["latest_expected_session"] == "2026-09-15"
    assert body["coverage"]["note"] is None
