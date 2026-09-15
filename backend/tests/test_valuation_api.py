"""Portfolio valuation API against PostgreSQL with seeded listings and prices."""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_now
from app.core.config import Settings
from app.main import create_app
from app.market_data.models import DailyPrice, Listing
from app.market_data.nse_calendar import NSE_TRADING_HOLIDAYS

MONDAY_EVENING = datetime(2026, 9, 14, 13, 0, tzinfo=UTC)  # 18:30 IST: expected session 14 Sep
TUESDAY_EVENING = datetime(2026, 9, 15, 13, 30, tzinfo=UTC)  # 19:00 IST: expected session 15 Sep
TEST_KEY = "test-key-not-a-real-credential"

SessionFactory = sessionmaker[Session]
MakeClient = Callable[..., TestClient]


@pytest.fixture
def make_client(migrated_database_url: str, clean_database: None) -> Iterator[MakeClient]:
    clients: list[TestClient] = []

    def _make(now: datetime = MONDAY_EVENING, **overrides: Any) -> TestClient:
        # Seeded prices treat Monday 14 Sep 2026 as a normal session, so the default here is a
        # plain weekday calendar. Tests of the real NSE calendar pass it explicitly.
        options = {"nse_trading_holidays": [], "nse_special_trading_sessions": [], **overrides}
        settings = Settings(_env_file=None, app_env="test", database_url=migrated_database_url, **options)
        app = create_app(settings)
        app.dependency_overrides[get_now] = lambda: now
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def add_listing(factory: SessionFactory, provider_id: str, name: str, *, nse: str | None = None, bse: str | None = None) -> uuid.UUID:
    with factory() as session:
        listing = Listing(
            provider="indian_api", provider_security_id=provider_id, name=name,
            nse_symbol=nse, bse_code=bse, last_seen_at=MONDAY_EVENING,
        )
        session.add(listing)
        session.commit()
        return listing.id


def add_price(factory: SessionFactory, listing_id: uuid.UUID, day: date, close: str) -> None:
    with factory() as session:
        session.add(
            DailyPrice(
                listing_id=listing_id, exchange="NSE", trade_date=day, close_price=Decimal(close),
                volume=1000, source="indian_api", fetched_at=MONDAY_EVENING,
            )
        )
        session.commit()


def create_portfolio(client: TestClient, *holdings: tuple[str, str, int, str]) -> str:
    payload = {
        "name": "Valuation test",
        "holdings": [
            {"exchange": exchange, "symbol": symbol, "quantity": quantity, "average_buy_price": price}
            for exchange, symbol, quantity, price in holdings
        ],
    }
    response = client.post("/api/v1/portfolios", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def valuation(client: TestClient, portfolio_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/portfolios/{portfolio_id}/valuation")
    assert response.status_code == 200, response.text
    return response.json()


def holding(body: dict[str, Any], symbol: str) -> dict[str, Any]:
    return next(item for item in body["holdings"] if item["symbol"] == symbol)


@pytest.fixture
def reliance(db_session_factory: SessionFactory) -> uuid.UUID:
    listing_id = add_listing(db_session_factory, "S0003018", "Reliance Industries", nse="RELIANCE", bse="500325")
    add_price(db_session_factory, listing_id, date(2026, 9, 11), "2600.00")
    add_price(db_session_factory, listing_id, date(2026, 9, 14), "2650.00")
    add_price(db_session_factory, listing_id, date(2026, 9, 10), "2590.00")
    return listing_id


def test_holding_is_valued_at_the_latest_dated_nse_close(make_client: MakeClient, reliance: uuid.UUID) -> None:
    client = make_client()
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "2400"))

    body = valuation(client, portfolio_id)
    item = holding(body, "RELIANCE")

    assert item["status"] == "VALUED"
    assert item["unpriced_reason"] is None
    assert item["price"]["close_price"] == "2650.00"
    assert item["price"]["trade_date"] == "2026-09-14"
    assert item["price"]["exchange"] == "NSE"
    assert item["price"]["source"] == "indian_api"
    assert item["price"]["source_name"] == "Indian API"
    assert item["invested_value"] == "24000.00"
    assert item["market_value"] == "26500.00"
    assert item["unrealized_pnl"] == "2500.00"
    assert item["unrealized_return_pct"] == "10.42"
    assert item["weight_pct"] == "100.00"
    assert item["warnings"] == []
    assert body["totals"] == {
        "total_invested_value": "24000.00",
        "priced_invested_value": "24000.00",
        "total_market_value": "26500.00",
        "total_unrealized_pnl": "2500.00",
        "total_unrealized_return_pct": "10.42",
        "is_complete": True,
    }
    assert body["freshness"] == {
        "expected_session_date": "2026-09-14",
        "latest_price_date": "2026-09-14",
        "oldest_price_date": "2026-09-14",
        "valued_count": 1,
        "stale_count": 0,
        "unpriced_count": 0,
    }
    assert body["methodology"]["price_basis"] == "NSE_EOD_CLOSE"
    assert "not personalized investment advice" in body["methodology"]["note"]
    assert body["valued_at"].startswith("2026-09-14T13:00:00")


def test_price_older_than_the_latest_expected_session_is_stale(make_client: MakeClient, reliance: uuid.UUID) -> None:
    client = make_client(now=TUESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "2400"))

    body = valuation(client, portfolio_id)
    item = holding(body, "RELIANCE")

    assert item["status"] == "STALE"
    assert item["market_value"] == "26500.00"
    assert item["price"]["trade_date"] == "2026-09-14"
    assert body["freshness"]["expected_session_date"] == "2026-09-15"
    assert body["freshness"]["stale_count"] == 1


@pytest.mark.parametrize(
    ("now", "expected_status", "expected_session"),
    [
        (datetime(2026, 9, 13, 8, 30, tzinfo=UTC), "VALUED", "2026-09-11"),  # Sunday 14:00 IST
        (datetime(2026, 9, 14, 4, 30, tzinfo=UTC), "VALUED", "2026-09-11"),  # Monday 10:00 IST, before EOD
        (MONDAY_EVENING, "STALE", "2026-09-14"),  # Monday 18:30 IST: Monday's close is now expected
    ],
)
def test_friday_close_over_the_weekend_follows_the_session_calendar(
    make_client: MakeClient, db_session_factory: SessionFactory, now: datetime, expected_status: str, expected_session: str
) -> None:
    listing_id = add_listing(db_session_factory, "S0003032", "Infosys", nse="INFY", bse="500209")
    add_price(db_session_factory, listing_id, date(2026, 9, 11), "1500.00")  # Friday
    client = make_client(now=now)
    portfolio_id = create_portfolio(client, ("NSE", "INFY", 4, "1400"))

    body = valuation(client, portfolio_id)
    item = holding(body, "INFY")

    assert item["status"] == expected_status
    assert item["price"]["trade_date"] == "2026-09-11"
    assert item["market_value"] == "6000.00"
    assert body["freshness"]["expected_session_date"] == expected_session


@pytest.mark.parametrize(
    ("now", "expected_status", "expected_session"),
    [
        (datetime(2026, 9, 14, 13, 30, tzinfo=UTC), "VALUED", "2026-09-11"),  # Mon 19:00 IST, Ganesh Chaturthi
        (datetime(2026, 9, 15, 11, 30, tzinfo=UTC), "VALUED", "2026-09-11"),  # Tue 17:00 IST, before EOD
        (datetime(2026, 9, 15, 13, 0, tzinfo=UTC), "STALE", "2026-09-15"),  # Tue 18:30 IST
    ],
)
def test_friday_close_stays_valued_through_the_ganesh_chaturthi_holiday(
    make_client: MakeClient, db_session_factory: SessionFactory, now: datetime, expected_status: str, expected_session: str
) -> None:
    listing_id = add_listing(db_session_factory, "S0003032", "Infosys", nse="INFY", bse="500209")
    add_price(db_session_factory, listing_id, date(2026, 9, 11), "1037.70")  # Friday close
    client = make_client(now=now, nse_trading_holidays=sorted(NSE_TRADING_HOLIDAYS))
    portfolio_id = create_portfolio(client, ("NSE", "INFY", 8, "1450"))

    body = valuation(client, portfolio_id)
    item = holding(body, "INFY")

    assert item["status"] == expected_status
    assert item["price"]["trade_date"] == "2026-09-11"
    assert body["freshness"]["expected_session_date"] == expected_session


def test_displayed_weights_sum_to_100_while_values_stay_exact(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    # Real closes from the M3A.1 validation; weights rounded one by one would sum to 100.01.
    closes = (
        (add_listing(db_session_factory, "S0003018", "Reliance Industries", nse="RELIANCE", bse="500325"), "1235.30"),
        (add_listing(db_session_factory, "S0003020", "HDFC Bank", nse="HDFCBANK", bse="500180"), "716.55"),
        (add_listing(db_session_factory, "S0003059", "Mahindra & Mahindra Ltd", nse="M&M", bse="500520"), "3029.50"),
    )
    for listing_id, close in closes:
        add_price(db_session_factory, listing_id, date(2026, 9, 14), close)
    client = make_client()
    portfolio_id = create_portfolio(
        client, ("BSE", "500325", 4, "1300"), ("NSE", "HDFCBANK", 6, "1700"), ("NSE", "M&M", 3, "2900")
    )

    body = valuation(client, portfolio_id)

    weights = {item["symbol"]: item["weight_pct"] for item in body["holdings"]}
    assert weights == {"500325": "26.96", "HDFCBANK": "23.46", "M&M": "49.58"}
    assert sum(Decimal(weight) for weight in weights.values()) == Decimal("100.00")
    assert [holding(body, symbol)["market_value"] for symbol in ("500325", "HDFCBANK", "M&M")] == [
        "4941.20", "4299.30", "9088.50",
    ]
    assert body["totals"]["total_market_value"] == "18329.00"
    assert body["totals"]["total_unrealized_pnl"] == "-5771.00"
    assert body["totals"]["total_unrealized_return_pct"] == "-23.95"
    assert "largest remainder" in body["methodology"]["rounding"]


def test_missing_price_is_unpriced_and_never_zero(
    make_client: MakeClient, reliance: uuid.UUID, db_session_factory: SessionFactory
) -> None:
    add_listing(db_session_factory, "S0003051", "Tata Consultancy Services", nse="TCS", bse="532540")
    client = make_client()
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "2400"), ("NSE", "TCS", 5, "3000"))

    body = valuation(client, portfolio_id)
    tcs = holding(body, "TCS")

    assert tcs["status"] == "UNPRICED"
    assert tcs["unpriced_reason"] == "NO_PRICE_DATA"
    assert tcs["price"] is None
    for field in ("market_value", "unrealized_pnl", "unrealized_return_pct", "weight_pct"):
        assert tcs[field] is None
    assert tcs["invested_value"] == "15000.00"
    assert holding(body, "RELIANCE")["weight_pct"] == "100.00"
    assert body["totals"]["total_invested_value"] == "39000.00"
    assert body["totals"]["priced_invested_value"] == "24000.00"
    assert body["totals"]["total_market_value"] == "26500.00"
    assert body["totals"]["total_unrealized_return_pct"] == "10.42"
    assert body["totals"]["is_complete"] is False
    assert body["freshness"]["unpriced_count"] == 1


def test_unknown_and_bse_only_holdings_are_unpriced_with_reasons(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    add_listing(db_session_factory, "S0000064", "UR Sugar Industries", bse="539097")
    client = make_client()
    portfolio_id = create_portfolio(client, ("NSE", "UNKNOWNCO", 1, "10"), ("BSE", "539097", 100, "25"))

    body = valuation(client, portfolio_id)

    assert holding(body, "UNKNOWNCO")["unpriced_reason"] == "LISTING_NOT_FOUND"
    assert holding(body, "539097")["unpriced_reason"] == "NO_NSE_LISTING"
    assert body["totals"]["total_market_value"] is None
    assert body["totals"]["total_unrealized_pnl"] is None
    assert body["totals"]["total_unrealized_return_pct"] is None
    assert body["totals"]["total_invested_value"] == "2510.00"
    assert body["freshness"]["latest_price_date"] is None


def test_bse_holding_is_valued_at_the_nse_close_of_the_same_security(make_client: MakeClient, reliance: uuid.UUID) -> None:
    client = make_client()
    portfolio_id = create_portfolio(client, ("BSE", "500325", 10, "2400"))

    item = holding(valuation(client, portfolio_id), "500325")

    assert item["exchange"] == "BSE"
    assert item["status"] == "VALUED"
    assert item["price"]["exchange"] == "NSE"
    assert item["market_value"] == "26500.00"


def test_losses_weights_and_portfolio_return(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    reliance_id = add_listing(db_session_factory, "S0003018", "Reliance Industries", nse="RELIANCE")
    tcs_id = add_listing(db_session_factory, "S0003051", "Tata Consultancy Services", nse="TCS")
    add_price(db_session_factory, reliance_id, date(2026, 9, 14), "2700.00")
    add_price(db_session_factory, tcs_id, date(2026, 9, 14), "3000.00")
    client = make_client()
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "2400"), ("NSE", "TCS", 6, "3500"))

    body = valuation(client, portfolio_id)

    assert holding(body, "RELIANCE")["weight_pct"] == "60.00"
    assert holding(body, "TCS")["weight_pct"] == "40.00"
    assert holding(body, "TCS")["unrealized_pnl"] == "-3000.00"
    assert holding(body, "TCS")["unrealized_return_pct"] == "-14.29"
    assert body["totals"]["total_market_value"] == "45000.00"
    assert body["totals"]["total_unrealized_pnl"] == "0.00"
    assert body["totals"]["total_unrealized_return_pct"] == "0.00"


def test_large_price_move_is_flagged(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    listing_id = add_listing(db_session_factory, "S0003018", "Reliance Industries", nse="RELIANCE")
    add_price(db_session_factory, listing_id, date(2026, 9, 11), "2640.00")
    add_price(db_session_factory, listing_id, date(2026, 9, 14), "1320.00")
    client = make_client()
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "2400"))

    assert holding(valuation(client, portfolio_id), "RELIANCE")["warnings"] == ["LARGE_PRICE_MOVE"]


def test_empty_portfolio_valuation(make_client: MakeClient) -> None:
    client = make_client()
    portfolio_id = create_portfolio(client)

    body = valuation(client, portfolio_id)

    assert body["holdings"] == []
    assert body["totals"]["total_invested_value"] == "0.00"
    assert body["totals"]["total_market_value"] is None
    assert body["totals"]["is_complete"] is True


def test_response_schema_is_stable(make_client: MakeClient, reliance: uuid.UUID) -> None:
    client = make_client()
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "2400"))

    body = valuation(client, portfolio_id)

    assert set(body) == {
        "portfolio_id", "portfolio_name", "valued_at", "market_data_configured",
        "methodology", "freshness", "totals", "holdings",
    }
    assert set(body["holdings"][0]) == {
        "holding_id", "symbol", "exchange", "quantity", "average_buy_price", "status", "unpriced_reason",
        "price", "invested_value", "market_value", "unrealized_pnl", "unrealized_return_pct", "weight_pct", "warnings",
    }
    assert set(body["holdings"][0]["price"]) == {"close_price", "trade_date", "exchange", "source", "source_name", "fetched_at"}


def test_nonexistent_portfolio_returns_404(make_client: MakeClient) -> None:
    response = make_client().get(f"/api/v1/portfolios/{uuid.uuid4()}/valuation")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "portfolio_not_found"


def test_valuation_without_database_returns_503(client: TestClient) -> None:
    response = client.get(f"/api/v1/portfolios/{uuid.uuid4()}/valuation")

    assert response.status_code == 503


def test_configuration_flag_is_reported_without_exposing_the_key(make_client: MakeClient, reliance: uuid.UUID) -> None:
    configured = make_client(indian_api_key=TEST_KEY)
    portfolio_id = create_portfolio(configured, ("NSE", "RELIANCE", 10, "2400"))

    response = configured.get(f"/api/v1/portfolios/{portfolio_id}/valuation")

    assert response.json()["market_data_configured"] is True
    assert TEST_KEY not in response.text
    assert valuation(make_client(), portfolio_id)["market_data_configured"] is False


def test_valuation_never_calls_the_market_data_provider(
    make_client: MakeClient, reliance: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.market_data.providers import indian_api

    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("valuation must not call the provider")

    # Patch the adapter itself (not httpx, which the test client also uses).
    monkeypatch.setattr(indian_api.IndianApiProvider, "__init__", forbidden)
    monkeypatch.setattr(indian_api.IndianApiProvider, "_request_json", forbidden)
    client = make_client(indian_api_key=TEST_KEY)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "2400"))

    assert valuation(client, portfolio_id)["totals"]["total_market_value"] == "26500.00"


def test_m2_portfolio_detail_is_unchanged(make_client: MakeClient, reliance: uuid.UUID) -> None:
    client = make_client()
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "2400"))

    body = client.get(f"/api/v1/portfolios/{portfolio_id}").json()

    assert set(body) == {"id", "name", "created_at", "updated_at", "holdings", "total_invested_capital"}
    assert body["total_invested_capital"] == "24000.00"
