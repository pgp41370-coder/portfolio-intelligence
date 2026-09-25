"""FIFO cost basis, realised and unrealised P&L, the portfolio timeline and attribution."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from app.performance import pnl as pnl_engine
from app.performance.positions import LedgerEvent
from test_performance_api import MakeClient, SessionFactory, seed  # noqa: F401
from test_transaction_performance import add_transactions, buy, sell  # noqa: F401
from test_valuation_api import add_listing, add_price, create_portfolio, make_client  # noqa: F401

MON, TUE, WED, THU, FRI = (date(2026, 9, day) for day in (14, 15, 16, 17, 18))
WEDNESDAY_EVENING = datetime(2026, 9, 16, 13, 0, tzinfo=UTC)
FRIDAY_EVENING = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)


def event(kind: str, day: date, quantity: int, price: str, fees: str = "0", symbol: str = "RELIANCE") -> LedgerEvent:
    return LedgerEvent(
        trade_date=day, symbol=symbol, exchange="NSE", kind=kind, quantity=quantity,
        price=Decimal(price), fees=Decimal(fees),
    )


def get(client: TestClient, portfolio_id: str, view: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"/api/v1/portfolios/{portfolio_id}/{view}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --- FIFO cost basis (no database) ---------------------------------------------------------


def test_fifo_matches_the_oldest_lot_first() -> None:
    ledger = pnl_engine.build_pnl([
        event("BUY", MON, 10, "100"),
        event("BUY", TUE, 10, "200"),
        event("SELL", WED, 10, "250"),
    ])

    entry = ledger.securities[("RELIANCE", "NSE")]
    assert entry.quantity == 10
    # The 100-rupee lot was sold, so the 200-rupee lot remains.
    assert entry.cost == Decimal(2000)
    assert entry.realised == Decimal(1500)  # 2,500 proceeds - 1,000 cost
    assert entry.average_cost == Decimal(200)


def test_a_partial_sale_consumes_part_of_a_lot() -> None:
    ledger = pnl_engine.build_pnl([event("BUY", MON, 10, "100"), event("SELL", TUE, 4, "150")])

    entry = ledger.securities[("RELIANCE", "NSE")]
    assert entry.quantity == 6 and entry.cost == Decimal(600)
    assert entry.realised == Decimal(200)  # 600 proceeds - 400 cost


def test_a_sale_spanning_two_lots_uses_both() -> None:
    ledger = pnl_engine.build_pnl([
        event("BUY", MON, 10, "100"),
        event("BUY", TUE, 10, "200"),
        event("SELL", WED, 15, "300"),
    ])

    entry = ledger.securities[("RELIANCE", "NSE")]
    assert entry.quantity == 5 and entry.cost == Decimal(1000)  # half the second lot
    assert entry.realised == Decimal(4500) - Decimal(2000)  # 10 x 100 + 5 x 200


def test_buy_fees_join_the_cost_and_are_allocated_pro_rata() -> None:
    ledger = pnl_engine.build_pnl([event("BUY", MON, 10, "100", fees="50"), event("SELL", TUE, 5, "100", fees="10")])

    entry = ledger.securities[("RELIANCE", "NSE")]
    # Half the lot sold takes half its fees: cost 500 + 25.
    assert entry.cost == Decimal(525)
    assert entry.realised == Decimal(490) - Decimal(525)  # proceeds 500 - 10 fees
    assert entry.fees == Decimal(60)


def test_selling_everything_leaves_no_cost_and_banks_the_profit() -> None:
    ledger = pnl_engine.build_pnl([event("BUY", MON, 10, "100"), event("SELL", TUE, 10, "130")])

    entry = ledger.securities[("RELIANCE", "NSE")]
    assert entry.quantity == 0 and entry.cost == Decimal(0)
    assert entry.realised == Decimal(300)
    assert ledger.contributions == Decimal(1000) and ledger.withdrawals == Decimal(1300)
    assert ledger.net_invested == Decimal(-300)


def test_a_same_day_buy_is_available_to_a_same_day_sale() -> None:
    """Buys are applied before sales on the same date, which is the only order that can work."""
    ledger = pnl_engine.build_pnl([event("SELL", MON, 5, "120"), event("BUY", MON, 10, "100")])

    entry = ledger.securities[("RELIANCE", "NSE")]
    assert entry.quantity == 5
    assert entry.realised == Decimal(100)  # 600 proceeds - 500 cost
    assert ledger.oversold == []


def test_unrealised_needs_a_price() -> None:
    assert pnl_engine.unrealised(10, Decimal(1000), None) is None
    assert pnl_engine.unrealised(10, Decimal(1000), Decimal(150)) == Decimal(500)
    assert pnl_engine.unrealised(0, Decimal(0), Decimal(150)) is None


def test_open_lots_show_what_is_left() -> None:
    lots = pnl_engine.open_lots_for(
        [event("BUY", MON, 10, "100"), event("BUY", TUE, 5, "200"), event("SELL", WED, 12, "300")],
        ("RELIANCE", "NSE"),
    )

    assert len(lots) == 1
    assert lots[0].quantity == 3 and lots[0].price == Decimal(200)


# --- P&L through the API ---------------------------------------------------------------------


def test_pnl_reports_realised_unrealised_and_flows(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "120"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 6, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100", fees="20"), sell("RELIANCE", TUE, 4, "110", fees="5"))

    body = get(client, portfolio_id, "pnl")

    security = body["securities"][0]
    assert security["quantity"] == 6
    assert security["cost_basis"] == "612.00"  # 600 + 12 of the 20 fees
    assert security["average_cost"] == "102.00"
    assert security["market_value"] == "720.00"  # 6 x 120
    assert security["realised_pnl"] == "27.00"  # 435 proceeds - 408 cost
    assert security["unrealised_pnl"] == "108.00"  # 720 - 612
    assert security["total_pnl"] == "135.00"
    totals = body["totals"]
    assert totals["contributions"] == "1020.00" and totals["withdrawals"] == "435.00"
    assert totals["net_invested"] == "585.00" and totals["fees"] == "25.00"
    assert totals["is_complete"] is True
    assert body["methodology"]["cost_basis"] == "FIFO"


def test_pnl_is_unavailable_without_a_ledger(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "90"))

    body = get(client, portfolio_id, "pnl")

    assert body["methodology"]["available"] is False
    assert body["totals"] is None and body["securities"] == []
    assert "no transaction ledger" in body["methodology"]["note"]


def test_pnl_withholds_totals_when_an_open_position_cannot_be_priced(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    add_listing(db_session_factory, "S2", "TCS", nse="TCS")  # listed, never priced
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "TCS", 10, "100"))
    add_transactions(client, portfolio_id, buy("TCS", MON, 10, "100"))

    body = get(client, portfolio_id, "pnl")

    assert body["totals"]["is_complete"] is False
    assert body["totals"]["total_pnl"] is None
    assert body["securities"][0]["unrealised_pnl"] is None
    assert "cannot be measured" in body["securities"][0]["price_note"]


# --- Timeline -----------------------------------------------------------------------------------


def test_timeline_lists_transactions_newest_first_with_their_effect(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "120"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 6, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), sell("RELIANCE", TUE, 4, "110"))

    body = get(client, portfolio_id, "timeline")

    assert body["basis"] == "TRANSACTIONS" and body["transaction_count"] == 2
    assert [entry["trade_date"] for entry in body["entries"]] == ["2026-09-15", "2026-09-14"]
    latest, first = body["entries"]
    assert latest["position_changes"] == ["RELIANCE -4 → 6"]
    assert latest["portfolio_value"] == "660.00"  # 6 x 110
    assert latest["net_cash_flow"] == "-440.00"
    assert first["position_changes"] == ["RELIANCE +10 → 10"]
    assert first["transactions"][0]["gross_value"] == "1000.00"


def test_timeline_shows_a_non_session_trade_on_the_session_it_is_recognised(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", date(2026, 9, 13), 10, "100"))  # a Sunday

    body = get(client, portfolio_id, "timeline")

    entry = body["entries"][0]
    assert entry["trade_date"] == "2026-09-14"  # recognised on Monday
    assert entry["transactions"][0]["trade_date"] == "2026-09-13"  # as entered
    assert "recognised" in body["note"]


def test_timeline_is_empty_without_a_ledger(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client)

    body = get(client, portfolio_id, "timeline")

    assert body["entries"] == [] and body["transaction_count"] == 0
    assert body["basis"] == "CURRENT_HOLDINGS"


# --- Attribution ---------------------------------------------------------------------------------


def test_contributions_sum_to_the_portfolio_return(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """The decomposition is checkable: the parts must add up to the whole."""
    seed(db_session_factory, "S1", "Up", "UPCO", {MON: "100", TUE: "120"})
    seed(db_session_factory, "S2", "Down", "DOWNCO", {MON: "100", TUE: "90"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "UPCO", 10, "100"), ("NSE", "DOWNCO", 10, "100"))
    add_transactions(client, portfolio_id, buy("UPCO", MON, 10, "100"), buy("DOWNCO", MON, 10, "100"))

    body = get(client, portfolio_id, "attribution")

    contributions = {item["symbol"]: Decimal(item["contribution_pct"]) for item in body["contributors"] + body["detractors"]}
    assert contributions["UPCO"] == Decimal("10.00")  # +200 on a 2,000 base
    assert contributions["DOWNCO"] == Decimal("-5.00")  # -100 on a 2,000 base
    assert Decimal(body["sum_of_daily_returns_pct"]) == Decimal("5.00")
    assert Decimal(body["twr_pct"]) == Decimal("5.00")  # one session, so no compounding gap


def test_a_purchase_is_not_counted_as_a_contribution_to_return(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "100", WED: "100"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 20, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), buy("RELIANCE", TUE, 10, "100"))

    body = get(client, portfolio_id, "attribution")

    assert body["contributors"] == [] and body["detractors"] == []
    assert Decimal(body["sum_of_daily_returns_pct"]) == Decimal("0.00")


def test_attribution_names_the_latest_session_movers(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Up", "UPCO", {MON: "100", TUE: "100", WED: "130"})
    seed(db_session_factory, "S2", "Down", "DOWNCO", {MON: "100", TUE: "100", WED: "80"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "UPCO", 10, "100"), ("NSE", "DOWNCO", 10, "100"))
    add_transactions(client, portfolio_id, buy("UPCO", MON, 10, "100"), buy("DOWNCO", MON, 10, "100"))

    body = get(client, portfolio_id, "attribution")

    assert body["latest_session"] == "2026-09-16"
    latest = {item["symbol"]: item for item in body["latest_contributions"]}
    assert latest["UPCO"]["contribution_pct"] == "15.00" and latest["UPCO"]["value_change"] == "300.00"
    assert latest["DOWNCO"]["contribution_pct"] == "-10.00"
    assert [item["symbol"] for item in body["latest_contributions"]] == ["UPCO", "DOWNCO"]  # best first


def test_attribution_reports_the_compounding_difference_rather_than_hiding_it(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "150", WED: "225"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = get(client, portfolio_id, "attribution")

    assert body["sum_of_daily_returns_pct"] == "100.00"  # 50% + 50%
    assert body["twr_pct"] == "125.00"  # 1.5 x 1.5 - 1
    assert body["compounding_difference_pct"] == "25.00"
    assert "differs from the compounded" in body["note"]


def test_attribution_flags_stale_positions(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=FRIDAY_EVENING)  # Wed, Thu and Fri have no stored close
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = get(client, portfolio_id, "attribution")

    assert body["stale_positions"] == ["RELIANCE on NSE"]


def test_attribution_without_a_ledger_uses_the_reconstruction_basis(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """Holdings alone still decompose; the basis says it is a reconstruction."""
    seed(db_session_factory, "S1", "Up", "UPCO", {MON: "100", TUE: "120"})
    seed(db_session_factory, "S2", "Down", "DOWNCO", {MON: "100", TUE: "90"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "UPCO", 10, "100"), ("NSE", "DOWNCO", 10, "100"))

    body = get(client, portfolio_id, "attribution")

    assert body["basis"] == "CURRENT_HOLDINGS"
    assert body["sessions_counted"] == 1
    assert [(item["symbol"], item["contribution_pct"]) for item in body["contributors"]] == [("UPCO", "10.00")]
    assert [(item["symbol"], item["contribution_pct"]) for item in body["detractors"]] == [("DOWNCO", "-5.00")]
    assert "no transaction ledger" in body["note"]
    assert "not what was actually held" in body["note"]


def test_reconstructed_attribution_matches_the_performance_series(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """The holdings valuation used for attribution must agree with the performance card's."""
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "121"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))

    attribution = get(client, portfolio_id, "attribution")
    performance = get(client, portfolio_id, "performance")

    assert attribution["period"] == performance["period"]
    assert attribution["sessions_counted"] == performance["summary"]["returns_used"]
    # One holding, so its contribution is the whole of each day's return.
    assert attribution["sum_of_daily_returns_pct"] == "20.00"  # 10% + 10%
    assert performance["summary"]["cumulative_return_pct"] == "21.00"  # compounded


def test_attribution_rejects_an_inverted_window(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client)

    response = client.get(
        f"/api/v1/portfolios/{portfolio_id}/attribution",
        params={"start_date": "2026-09-16", "end_date": "2026-09-14"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_date_range"


def test_the_new_views_never_call_the_market_data_provider(
    make_client: MakeClient, db_session_factory: SessionFactory, monkeypatch: Any
) -> None:
    from app.market_data.providers.indian_api import IndianApiProvider

    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    def explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the analytics endpoints must not call the provider")

    monkeypatch.setattr(IndianApiProvider, "_request_json", explode)

    for view in ("pnl", "timeline", "attribution"):
        assert get(client, portfolio_id, view)
