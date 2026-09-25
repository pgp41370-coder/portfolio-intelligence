"""Deterministic portfolio intelligence: structured facts composed from measured numbers.

The rules this layer must keep are testable, so they are tested: contributions reconcile to the
measured return, ranking is deterministic, nothing is fabricated when data is missing, and no
response ever recommends anything.
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

MON, TUE, WED, THU, FRI = (date(2026, 9, day) for day in (14, 15, 16, 17, 18))
TUESDAY_EVENING = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)
WEDNESDAY_EVENING = datetime(2026, 9, 16, 13, 0, tzinfo=UTC)
FRIDAY_EVENING = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)

# Words this layer must never use about a security or a portfolio.
FORBIDDEN = (
    "should", "recommend", "buy ", "sell ", "attractive", "unattractive", "good investment",
    "bad investment", "will rise", "will fall", "risky", "safe", "undervalued", "overvalued",
    "outperform will", "predict", "forecast", "expected to",
)


def intelligence(client: TestClient, portfolio_id: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"/api/v1/portfolios/{portfolio_id}/intelligence", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def all_text(body: dict[str, Any]) -> str:
    """Every sentence the response would show a reader."""
    parts = [body["headline"], body["methodology"], *body["findings"]]
    for section in ("returns", "cash_flow", "risk", "data_quality"):
        if body.get(section):
            parts.append(body[section].get("note") or "")
            parts.extend(body[section].get("limitations") or [])
    return " ".join(parts).lower()


def register_benchmark(monkeypatch: pytest.MonkeyPatch, symbol: str = "SETFNIF50") -> None:
    monkeypatch.setitem(
        registry.BENCHMARKS,
        "TESTBM",
        registry.BenchmarkDefinition(
            key="TESTBM",
            display_name="Test index ETF",
            nse_symbol=symbol,
            exchange=Exchange.NSE,
            tracks="Test index",
            source="test fixture",
            is_proxy=True,
            methodology="Daily closes rebased to 100.",
            note="ETF proxy, not the index itself.",
        ),
    )


# --- 1-4. Contributors, detractors, zero contribution, ties ---------------------------------


def test_positive_and_negative_contributors_are_named_and_ranked(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Big win", "BIGUP", {MON: "100", TUE: "140"})
    seed(db_session_factory, "S2", "Small win", "SMALLUP", {MON: "100", TUE: "110"})
    seed(db_session_factory, "S3", "Loser", "DOWNCO", {MON: "100", TUE: "70"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(
        client, ("NSE", "BIGUP", 10, "100"), ("NSE", "SMALLUP", 10, "100"), ("NSE", "DOWNCO", 10, "100")
    )
    add_transactions(
        client, portfolio_id, buy("BIGUP", MON, 10, "100"), buy("SMALLUP", MON, 10, "100"), buy("DOWNCO", MON, 10, "100")
    )

    body = intelligence(client, portfolio_id)

    positive = body["returns"]["top_positive"]
    negative = body["returns"]["top_negative"]
    # 3,000 opening value: +400 / +100 / -300 are 13.33, 3.33 and -10.00 points.
    assert [(item["rank"], item["symbol"], item["contribution_pct"]) for item in positive] == [
        (1, "BIGUP", "13.33"),
        (2, "SMALLUP", "3.33"),
    ]
    assert [(item["rank"], item["symbol"], item["contribution_pct"]) for item in negative] == [(1, "DOWNCO", "-10.00")]
    assert "largest positive contribution came from BIGUP" in " ".join(body["findings"])
    assert "largest negative contribution came from DOWNCO" in " ".join(body["findings"])


def test_contributions_reconcile_to_the_measured_return(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """The identity that makes this an explanation rather than a guess."""
    seed(db_session_factory, "S1", "Up", "UPCO", {MON: "100", TUE: "120", WED: "130"})
    seed(db_session_factory, "S2", "Down", "DOWNCO", {MON: "100", TUE: "90", WED: "95"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "UPCO", 10, "100"), ("NSE", "DOWNCO", 10, "100"))
    add_transactions(client, portfolio_id, buy("UPCO", MON, 10, "100"), buy("DOWNCO", MON, 10, "100"))

    body = intelligence(client, portfolio_id)

    returns = body["returns"]
    assert returns["contributions_reconcile"] is True
    total = sum(Decimal(item["contribution_pct"]) for item in returns["top_positive"] + returns["top_negative"])
    assert total == Decimal(returns["sum_of_contributions_pct"])
    # The compounded return is a different number, and the difference is stated, not hidden.
    assert returns["portfolio_return_pct"] != returns["sum_of_contributions_pct"]
    assert Decimal(returns["compounding_difference_pct"]) == Decimal(returns["portfolio_return_pct"]) - total


def test_a_security_that_did_not_move_contributes_zero_and_is_not_ranked(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Mover", "MOVER", {MON: "100", TUE: "120"})
    seed(db_session_factory, "S2", "Flat", "FLATCO", {MON: "100", TUE: "100"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "MOVER", 10, "100"), ("NSE", "FLATCO", 10, "100"))
    add_transactions(client, portfolio_id, buy("MOVER", MON, 10, "100"), buy("FLATCO", MON, 10, "100"))

    body = intelligence(client, portfolio_id)

    named = [item["symbol"] for item in body["returns"]["top_positive"] + body["returns"]["top_negative"]]
    assert named == ["MOVER"]  # a zero contribution is neither a contributor nor a detractor
    assert body["returns"]["contributions_reconcile"] is True


def test_tied_contributions_are_ordered_deterministically(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """Identical numbers must not shuffle between requests; the tie breaks on symbol."""
    for provider_id, symbol in (("S1", "ZED"), ("S2", "ALPHA"), ("S3", "MIDCO")):
        seed(db_session_factory, provider_id, symbol.title(), symbol, {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(
        client, ("NSE", "ZED", 10, "100"), ("NSE", "ALPHA", 10, "100"), ("NSE", "MIDCO", 10, "100")
    )
    add_transactions(
        client, portfolio_id, buy("ZED", MON, 10, "100"), buy("ALPHA", MON, 10, "100"), buy("MIDCO", MON, 10, "100")
    )

    first = intelligence(client, portfolio_id, top=5)
    second = intelligence(client, portfolio_id, top=5)

    order = [item["symbol"] for item in first["returns"]["top_positive"]]
    assert order == ["ALPHA", "MIDCO", "ZED"]  # equal contributions, alphabetical
    assert order == [item["symbol"] for item in second["returns"]["top_positive"]]
    assert [item["rank"] for item in first["returns"]["top_positive"]] == [1, 2, 3]


# --- 5-6. Benchmark available and unavailable ------------------------------------------------


def test_benchmark_comparison_is_stated_as_a_proxy(
    make_client: MakeClient, db_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    seed(db_session_factory, "S2", "Index ETF", "SETFNIF50", {MON: "200", TUE: "210"})
    register_benchmark(monkeypatch)
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = intelligence(client, portfolio_id, benchmark="TESTBM")

    assert body["returns"]["benchmark_return_pct"] == "5.00"
    assert body["returns"]["relative_return_pct"] == "5.00"  # 10.00 - 5.00
    assert body["data_quality"]["benchmark_basis"] == "ETF_PROXY"
    assert "benchmark proxy" in body["headline"]
    # Never called the index itself.
    assert "nifty 50 index" not in all_text(body)


def test_an_unavailable_benchmark_is_explained_not_invented(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = intelligence(client, portfolio_id, benchmark="NIFTY50")

    assert body["returns"]["benchmark_return_pct"] is None
    assert body["returns"]["relative_return_pct"] is None
    assert body["data_quality"]["benchmark_status"] == "no_data"
    assert any("No benchmark comparison" in item for item in body["data_quality"]["limitations"])
    assert "benchmark proxy" not in body["headline"]


# --- 7-9. Coverage, staleness, missing sessions ------------------------------------------------


def test_complete_coverage_reports_available(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = intelligence(client, portfolio_id)

    assert body["data_quality"]["coverage_status"] == "complete"
    assert body["data_quality"]["sessions_behind_latest"] == 0
    assert body["status"] == "available"
    assert body["data_quality"]["limitations"] == []


def test_stale_prices_are_disclosed_and_downgrade_the_status(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=FRIDAY_EVENING)  # Wed, Thu, Fri have no stored close
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = intelligence(client, portfolio_id)

    assert body["status"] == "limited"
    assert body["data_quality"]["sessions_behind_latest"] == 3
    assert any("3 sessions behind" in item for item in body["data_quality"]["limitations"])
    assert body["data_quality"]["stale_securities"] == ["RELIANCE on NSE"]
    assert any("behind the latest completed NSE session" in finding for finding in body["findings"])


def test_a_missing_session_is_counted_and_never_filled(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", WED: "121"})  # no Tuesday
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = intelligence(client, portfolio_id)

    assert body["data_quality"]["coverage_status"] == "partial"
    assert body["data_quality"]["missing_session_count"] == 1
    assert any("could not be valued" in item for item in body["data_quality"]["limitations"])
    assert body["status"] == "limited"
    # No return could be measured across the gap, so none is claimed.
    assert body["returns"]["portfolio_return_pct"] is None


# --- 10-12. Cash flow -----------------------------------------------------------------------------


def test_a_contribution_is_not_reported_as_performance(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "100", WED: "100"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 110, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), buy("RELIANCE", TUE, 100, "100"))

    body = intelligence(client, portfolio_id)

    cash = body["cash_flow"]
    assert cash["value_change"] == "10000.00"  # 1,000 -> 11,000
    assert cash["net_external_flow"] == "11000.00"
    assert cash["return_driven_change"] == "-1000.00"
    assert cash["twr_pct"] == "0.00"  # flat prices: no performance at all
    assert any("not equivalent to investment performance" in finding for finding in body["findings"])


def test_a_withdrawal_is_reported_as_a_flow_not_a_loss(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "110"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 2, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"), sell("RELIANCE", TUE, 8, "110"))

    body = intelligence(client, portfolio_id)

    cash = body["cash_flow"]
    assert cash["withdrawals"] == "880.00"
    assert Decimal(cash["value_change"]) < 0  # the portfolio is smaller
    assert cash["twr_pct"] == "10.00"  # but the return is positive
    assert body["risk"]["max_drawdown_pct"] == "0.00"  # a withdrawal is not a drawdown


def test_the_cash_flow_section_says_so_when_there_is_no_ledger(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))

    body = intelligence(client, portfolio_id)

    assert body["cash_flow"]["net_external_flow"] == "0.00"
    assert body["cash_flow"]["contributions"] is None
    assert "no transaction ledger" in body["cash_flow"]["note"]


# --- 13-17. Portfolio shapes -----------------------------------------------------------------------


def test_a_holdings_only_portfolio_is_explained_on_the_reconstruction_basis(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Up", "UPCO", {MON: "100", TUE: "120"})
    seed(db_session_factory, "S2", "Down", "DOWNCO", {MON: "100", TUE: "90"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "UPCO", 10, "100"), ("NSE", "DOWNCO", 10, "100"))

    body = intelligence(client, portfolio_id)

    assert body["returns"]["basis"] == "CURRENT_HOLDINGS"
    assert body["returns"]["calculation_method"] == "PRICE_RETURN_ENDPOINTS"
    assert [item["symbol"] for item in body["returns"]["top_positive"]] == ["UPCO"]
    assert [item["symbol"] for item in body["returns"]["top_negative"]] == ["DOWNCO"]
    assert "today's holdings valued at past closes" in body["headline"]


def test_an_empty_portfolio_explains_that_there_is_nothing_to_measure(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client)

    body = intelligence(client, portfolio_id)

    assert body["status"] == "unavailable"
    assert body["returns"] is None and body["cash_flow"] is None and body["risk"] is None
    assert body["findings"] == []
    assert "not enough priced history" in body["headline"].lower()


def test_a_single_security_portfolio_attributes_everything_to_it(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = intelligence(client, portfolio_id)

    assert [(item["symbol"], item["contribution_pct"]) for item in body["returns"]["top_positive"]] == [
        ("RELIANCE", "10.00")
    ]
    assert body["returns"]["top_positive"][0]["security_return_pct"] == "10.00"
    assert body["risk"]["largest_position_weight_pct"] == "100.00"
    assert body["risk"]["concentration_band"] == "highly concentrated"


def test_a_portfolio_that_did_not_move_reports_zero_not_silence(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "100", WED: "100"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = intelligence(client, portfolio_id)

    assert body["returns"]["portfolio_return_pct"] == "0.00"
    assert body["returns"]["top_positive"] == [] and body["returns"]["top_negative"] == []
    assert body["risk"]["positive_sessions"] == 0 and body["risk"]["negative_sessions"] == 0
    assert body["risk"]["flat_sessions"] == 2
    assert body["risk"]["current_drawdown_pct"] == "0.00"


def test_a_portfolio_with_no_priced_holdings_is_unavailable(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    add_listing(db_session_factory, "S2", "TCS", nse="TCS")  # listed, never priced
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "TCS", 10, "100"))

    body = intelligence(client, portfolio_id)

    assert body["status"] == "unavailable"
    assert body["returns"] is None
    assert body["data_quality"]["limitations"]


# --- 18-20. Reconciliation, determinism, no fabrication ---------------------------------------------


def test_a_ledger_that_disagrees_with_holdings_is_disclosed(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 25, "100"))  # holdings say 25
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))  # ledger says 10

    body = intelligence(client, portfolio_id)

    assert body["data_quality"]["reconciliation_status"] == "differs"
    assert any("disagree" in item for item in body["data_quality"]["limitations"])
    assert body["status"] == "limited"


def test_the_whole_response_is_deterministic(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Up", "UPCO", {MON: "100", TUE: "120", WED: "115"})
    seed(db_session_factory, "S2", "Down", "DOWNCO", {MON: "100", TUE: "90", WED: "95"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "UPCO", 10, "100"), ("NSE", "DOWNCO", 10, "100"))
    add_transactions(client, portfolio_id, buy("UPCO", MON, 10, "100"), buy("DOWNCO", MON, 10, "100"))

    first = intelligence(client, portfolio_id)
    second = intelligence(client, portfolio_id)

    for section in ("headline", "findings", "returns", "cash_flow", "risk", "data_quality"):
        assert first[section] == second[section], section


def test_no_response_gives_advice_or_predicts_anything(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """The explanation layer states measurements; it never tells anyone what to do."""
    seed(db_session_factory, "S1", "Up", "UPCO", {MON: "100", TUE: "140"})
    seed(db_session_factory, "S2", "Down", "DOWNCO", {MON: "100", TUE: "60"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "UPCO", 10, "100"), ("NSE", "DOWNCO", 10, "100"))
    add_transactions(client, portfolio_id, buy("UPCO", MON, 10, "100"), buy("DOWNCO", MON, 10, "100"))

    text = all_text(intelligence(client, portfolio_id))

    for phrase in FORBIDDEN:
        assert phrase not in text, f"the explanation used {phrase!r}"


def test_nothing_is_reported_that_was_not_measured(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """Short history: volatility, beta and the rest are withheld rather than estimated."""
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = intelligence(client, portfolio_id)

    risk = body["risk"]
    assert risk["volatility_pct"] is None  # needs 20 returns
    assert risk["downside_volatility_pct"] is None
    assert risk["beta"] is None  # needs a benchmark and 20 paired returns
    assert body["returns"]["benchmark_return_pct"] is None
    # What it does have, it reports.
    assert risk["max_drawdown_pct"] == "0.00" and risk["positive_sessions"] == 1


# --- Endpoint behaviour -------------------------------------------------------------------------------


def test_intelligence_is_read_only_and_needs_a_known_portfolio(make_client: MakeClient) -> None:
    client = make_client(now=TUESDAY_EVENING)
    unknown = "00000000-0000-0000-0000-000000000000"

    assert client.get(f"/api/v1/portfolios/{unknown}/intelligence").status_code == 404
    assert client.post(f"/api/v1/portfolios/{unknown}/intelligence").status_code == 405


def test_an_inverted_window_is_rejected(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client)

    response = client.get(
        f"/api/v1/portfolios/{portfolio_id}/intelligence",
        params={"start_date": "2026-09-16", "end_date": "2026-09-14"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_date_range"


def test_intelligence_never_calls_the_market_data_provider(
    make_client: MakeClient, db_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.market_data.providers.indian_api import IndianApiProvider

    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    def explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("intelligence must not call the provider")

    monkeypatch.setattr(IndianApiProvider, "_request_json", explode)

    assert intelligence(client, portfolio_id)["status"] in {"available", "limited"}


def test_intelligence_is_available_in_production_because_it_only_reads(
    migrated_database_url: str,
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
        read = client.get("/api/v1/portfolios/00000000-0000-0000-0000-000000000000/intelligence")
        written = client.post("/api/v1/portfolios/00000000-0000-0000-0000-000000000000/intelligence")

    assert read.status_code == 404  # reached the handler; the portfolio simply does not exist
    assert written.status_code == 403 and written.json()["error"]["code"] == "read_only_demo"


# --- Explanation trace (M5.1) -------------------------------------------------------------


def test_the_trace_is_absent_unless_asked_for(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    assert intelligence(client, portfolio_id)["trace"] is None
    assert intelligence(client, portfolio_id, trace=True)["trace"]


def test_the_trace_explains_where_each_headline_figure_came_from(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Up", "UPCO", {MON: "100", TUE: "120"})
    seed(db_session_factory, "S2", "Down", "DOWNCO", {MON: "100", TUE: "90"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "UPCO", 10, "100"), ("NSE", "DOWNCO", 10, "100"))
    add_transactions(client, portfolio_id, buy("UPCO", MON, 10, "100"), buy("DOWNCO", MON, 10, "100"))

    body = intelligence(client, portfolio_id, trace=True)

    by_metric = {entry["metric"]: entry for entry in body["trace"]}
    assert "portfolio_return_pct" in by_metric
    assert "contribution:UPCO" in by_metric and "contribution:DOWNCO" in by_metric

    traced = by_metric["portfolio_return_pct"]
    assert traced["value"] == body["returns"]["portfolio_return_pct"]  # published precision
    assert "flow_adjusted_returns" in traced["source"]
    assert "V_(t-1)" in traced["formula"]
    assert traced["inputs"]["start_value"] == body["cash_flow"]["start_value"]

    contribution = by_metric["contribution:UPCO"]
    assert contribution["value"] == "10.00"
    assert contribution["source"].endswith("attribute")
    assert contribution["inputs"]["net_flow"] == "1000.00"


def test_every_traced_value_matches_what_the_response_published(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """A trace that disagreed with the figure it explains would be worse than none."""
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110", WED: "99"})
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    body = intelligence(client, portfolio_id, trace=True)

    by_metric = {entry["metric"]: entry["value"] for entry in body["trace"]}
    assert by_metric["portfolio_return_pct"] == body["returns"]["portfolio_return_pct"]
    assert by_metric["sum_of_contributions_pct"] == body["returns"]["sum_of_contributions_pct"]
    assert by_metric["max_drawdown_pct"] == body["risk"]["max_drawdown_pct"]
    assert by_metric["current_drawdown_pct"] == body["risk"]["current_drawdown_pct"]
    assert by_metric["return_driven_change"] == body["cash_flow"]["return_driven_change"]


def test_the_trace_carries_no_advice_either(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Up", "UPCO", {MON: "100", TUE: "140"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "UPCO", 10, "100"))
    add_transactions(client, portfolio_id, buy("UPCO", MON, 10, "100"))

    body = intelligence(client, portfolio_id, trace=True)

    text = " ".join(
        f"{entry['metric']} {entry['source']} {entry['formula']}" for entry in body["trace"]
    ).lower()
    for phrase in FORBIDDEN:
        assert phrase not in text, f"the trace used {phrase!r}"


# --- Wording review (M5.1) -------------------------------------------------------------------


def test_findings_describe_contribution_without_claiming_causation(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """"Contributed" is measured. "Caused", "because" and "due to" are not."""
    seed(db_session_factory, "S1", "Up", "UPCO", {MON: "100", TUE: "140"})
    seed(db_session_factory, "S2", "Down", "DOWNCO", {MON: "100", TUE: "60"})
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "UPCO", 10, "100"), ("NSE", "DOWNCO", 10, "100"))
    add_transactions(client, portfolio_id, buy("UPCO", MON, 10, "100"), buy("DOWNCO", MON, 10, "100"))

    body = intelligence(client, portfolio_id)
    text = all_text(body).lower()

    for phrase in ("caused", "because the", "due to", "as a result of", "driven by the fact"):
        assert phrase not in text, f"the explanation implied causation with {phrase!r}"
    assert "contribution came from" in text  # what it does say


def test_the_benchmark_is_never_described_as_the_index(
    make_client: MakeClient, db_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", {MON: "100", TUE: "110"})
    seed(db_session_factory, "S2", "Index ETF", "SETFNIF50", {MON: "200", TUE: "210"})
    register_benchmark(monkeypatch)
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "100"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "100"))

    text = all_text(intelligence(client, portfolio_id, benchmark="TESTBM"))

    assert "benchmark proxy" in text
    for phrase in ("the index returned", "versus the index", "the nifty 50 returned"):
        assert phrase not in text
