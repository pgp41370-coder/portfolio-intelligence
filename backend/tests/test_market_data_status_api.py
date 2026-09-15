"""Market-data status endpoint and market-data settings."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_now
from app.core.config import Settings
from app.main import create_app
from app.market_data.models import DailyPrice, Listing, MarketDataSyncRun

MONDAY_EVENING = datetime(2026, 9, 14, 13, 0, tzinfo=UTC)
TEST_KEY = "test-key-not-a-real-credential"


@pytest.fixture
def status_client(migrated_database_url: str, clean_database: None) -> Iterator[Any]:
    clients: list[TestClient] = []

    def _make(**overrides: Any) -> TestClient:
        settings = Settings(_env_file=None, app_env="test", database_url=migrated_database_url, **overrides)
        app = create_app(settings)
        app.dependency_overrides[get_now] = lambda: MONDAY_EVENING
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def test_status_before_any_sync(status_client: Any) -> None:
    body = status_client().get("/api/v1/market-data/status").json()

    assert body == {
        "provider": "indian_api",
        "provider_name": "Indian API",
        "configured": False,
        "price_basis": "NSE_EOD_CLOSE",
        "monthly_request_budget": 450,
        "requests_used_this_month": 0,
        "active_listings": 0,
        "securities_with_prices": 0,
        "latest_trade_date": None,
        "expected_session_date": "2026-09-14",
        "last_listing_sync": None,
        "last_price_sync": None,
        "last_successful_price_sync_at": None,
        "held_securities": {"valued": 0, "stale": 0, "unpriced": 0},
    }


def test_status_reports_runs_usage_and_freshness(
    status_client: Any, db_session_factory: sessionmaker[Session]
) -> None:
    later = datetime(2026, 9, 14, 14, 0, tzinfo=UTC)
    with db_session_factory() as session:
        reliance = Listing(provider="indian_api", provider_security_id="S0003018", name="Reliance Industries", nse_symbol="RELIANCE", last_seen_at=MONDAY_EVENING)
        tcs = Listing(provider="indian_api", provider_security_id="S0003051", name="Tata Consultancy Services", nse_symbol="TCS", last_seen_at=MONDAY_EVENING)
        session.add_all([reliance, tcs])
        session.flush()
        session.add_all(
            [
                DailyPrice(listing_id=reliance.id, exchange="NSE", trade_date=date(2026, 9, 14), close_price=Decimal("2650"), source="indian_api", fetched_at=MONDAY_EVENING),
                DailyPrice(listing_id=tcs.id, exchange="NSE", trade_date=date(2026, 9, 11), close_price=Decimal("3188.90"), source="indian_api", fetched_at=MONDAY_EVENING),
                MarketDataSyncRun(provider="indian_api", kind="security_master", status="succeeded", started_at=MONDAY_EVENING, completed_at=MONDAY_EVENING, details={}),
                MarketDataSyncRun(provider="indian_api", kind="daily_prices", status="succeeded", started_at=MONDAY_EVENING, completed_at=MONDAY_EVENING, requests_made=3, records_attempted=3, records_inserted=7, details={}),
                MarketDataSyncRun(provider="indian_api", kind="daily_prices", status="partial", started_at=later, completed_at=later, requests_made=2, records_attempted=2, failures=1, error_summary="1 of 2 securities could not be updated.", details={}),
                MarketDataSyncRun(provider="indian_api", kind="daily_prices", status="succeeded", started_at=datetime(2026, 8, 20, tzinfo=UTC), completed_at=datetime(2026, 8, 20, tzinfo=UTC), requests_made=300, details={}),
            ]
        )
        session.commit()
    client = status_client(indian_api_key=TEST_KEY)
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Status", "holdings": [
            {"symbol": "RELIANCE", "exchange": "NSE", "quantity": 1, "average_buy_price": "1"},
            {"symbol": "TCS", "exchange": "NSE", "quantity": 1, "average_buy_price": "1"},
            {"symbol": "UNKNOWNCO", "exchange": "NSE", "quantity": 1, "average_buy_price": "1"},
        ]},
    )
    assert created.status_code == 201

    response = client.get("/api/v1/market-data/status")
    body = response.json()

    assert body["configured"] is True
    assert TEST_KEY not in response.text
    assert body["requests_used_this_month"] == 5
    assert body["active_listings"] == 2
    assert body["securities_with_prices"] == 2
    assert body["latest_trade_date"] == "2026-09-14"
    assert body["last_listing_sync"]["status"] == "succeeded"
    assert body["last_price_sync"]["status"] == "partial"
    assert body["last_price_sync"]["error_summary"] == "1 of 2 securities could not be updated."
    assert datetime.fromisoformat(body["last_successful_price_sync_at"]) == MONDAY_EVENING
    assert body["held_securities"] == {"valued": 1, "stale": 1, "unpriced": 1}


def test_status_without_database_returns_503(client: TestClient) -> None:
    assert client.get("/api/v1/market-data/status").status_code == 503


def test_blank_api_key_means_not_configured() -> None:
    settings = Settings(_env_file=None, indian_api_key="   ")

    assert settings.indian_api_key is None
    assert settings.market_data_configured is False


def test_api_key_is_hidden_in_settings_repr() -> None:
    settings = Settings(_env_file=None, indian_api_key=TEST_KEY)

    assert settings.market_data_configured is True
    assert TEST_KEY not in repr(settings)
    assert TEST_KEY not in str(settings.model_dump())


@pytest.mark.parametrize(
    "overrides",
    [
        {"indian_api_base_url": "http://stock.indianapi.in"},
        {"indian_api_security_master_url": "ftp://example.com/list.json"},
        {"market_data_monthly_request_budget": 501},
        {"market_data_monthly_request_budget": 0},
        {"market_data_min_request_interval_seconds": 1.0},
        {"market_data_backfill_period": "max"},
    ],
)
def test_unsafe_market_data_settings_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)
