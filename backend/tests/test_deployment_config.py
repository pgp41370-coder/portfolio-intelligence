"""Production configuration: read-only public API, CORS, API docs, database pooling and sync guards."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.database import get_engine
from app.main import create_app
from app.market_data import cli

PRODUCTION_ORIGIN = "https://portfolio-intelligence-bice.vercel.app"
ZERO_ID = "00000000-0000-0000-0000-000000000000"
CSV_FILE = ("holdings.csv", b"symbol,exchange,quantity,average_buy_price\nTCS,NSE,1,3000\n", "text/csv")


def production_settings(**overrides: Any) -> Settings:
    options: dict[str, Any] = {"app_env": "production", "database_url": None, "cors_allowed_origins": [PRODUCTION_ORIGIN]}
    options.update(overrides)
    return Settings(_env_file=None, **options)


# --- Read-only public API --------------------------------------------------------------


WRITE_REQUESTS = [
    ("POST", "/api/v1/portfolios", {"json": {"name": "Attempt", "holdings": []}}),
    ("POST", "/api/v1/portfolios/csv-preview", {"files": {"file": CSV_FILE}}),
    ("POST", "/api/v1/portfolios/csv-import", {"data": {"name": "Attempt"}, "files": {"file": CSV_FILE}}),
    (
        "POST",
        f"/api/v1/portfolios/{ZERO_ID}/holdings",
        {"json": {"symbol": "TCS", "exchange": "NSE", "quantity": 1, "average_buy_price": "1"}},
    ),
    ("DELETE", f"/api/v1/portfolios/{ZERO_ID}/holdings/{ZERO_ID}", {}),
    ("PUT", f"/api/v1/portfolios/{ZERO_ID}", {"json": {}}),
    ("PATCH", f"/api/v1/portfolios/{ZERO_ID}", {"json": {}}),
    ("POST", "/health", {}),
]


@pytest.mark.parametrize(("method", "path", "kwargs"), WRITE_REQUESTS)
def test_production_rejects_every_write(method: str, path: str, kwargs: dict[str, Any]) -> None:
    with TestClient(create_app(production_settings())) as client:
        response = client.request(method, path, **kwargs)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "read_only_demo"
    assert "read-only" in response.json()["error"]["message"]


def test_production_rejects_an_oversized_upload_without_reading_it() -> None:
    too_large = ("holdings.csv", b"x" * (2 * 1024 * 1024), "text/csv")
    with TestClient(create_app(production_settings())) as client:
        response = client.post("/api/v1/portfolios/csv-import", data={"name": "Attempt"}, files={"file": too_large})

    assert response.status_code == 403  # the read-only guard runs before the upload limit and parsing


def test_production_reads_reach_their_routes() -> None:
    with TestClient(create_app(production_settings())) as client:
        assert client.get("/health").json() == {"status": "ok"}
        # No database is configured in this test, so reads return 503 rather than 403.
        assert client.get("/api/v1/portfolios").status_code == 503
        assert client.get(f"/api/v1/portfolios/{ZERO_ID}/valuation").status_code == 503
        assert client.get("/api/v1/market-data/status").status_code == 503


def test_writes_are_enabled_outside_production_and_can_be_enabled_explicitly() -> None:
    assert Settings(_env_file=None, app_env="development").write_api_enabled is True
    assert Settings(_env_file=None, app_env="test").write_api_enabled is True
    assert production_settings().write_api_enabled is False
    assert production_settings(enable_write_api=True).write_api_enabled is True
    assert Settings(_env_file=None, app_env="development", enable_write_api=False).write_api_enabled is False

    with TestClient(create_app(Settings(_env_file=None, app_env="test", database_url=None))) as client:
        # Reaches the route (no database configured) instead of the read-only guard.
        assert client.post("/api/v1/portfolios", json={"name": "Allowed", "holdings": []}).status_code == 503


# --- API docs and CORS -----------------------------------------------------------------


def test_api_docs_are_disabled_in_production() -> None:
    with TestClient(create_app(production_settings())) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
    with TestClient(create_app(Settings(_env_file=None, app_env="test", database_url=None))) as client:
        assert client.get("/openapi.json").status_code == 200


def test_production_cors_allows_only_the_configured_origin() -> None:
    with TestClient(create_app(production_settings())) as client:
        allowed = client.options(
            "/api/v1/portfolios", headers={"Origin": PRODUCTION_ORIGIN, "Access-Control-Request-Method": "GET"}
        )
        other = client.get("/health", headers={"Origin": "https://attacker.example"})
        other_preflight = client.options(
            "/api/v1/portfolios", headers={"Origin": "https://attacker.example", "Access-Control-Request-Method": "GET"}
        )

    assert allowed.headers["access-control-allow-origin"] == PRODUCTION_ORIGIN
    assert "access-control-allow-origin" not in other.headers
    assert "access-control-allow-origin" not in other_preflight.headers


def test_cors_defaults_depend_on_the_environment() -> None:
    assert Settings(_env_file=None, app_env="development").cors_allowed_origins == ["http://localhost:3000"]
    assert Settings(_env_file=None, app_env="test").cors_allowed_origins == ["http://localhost:3000"]
    assert Settings(_env_file=None, app_env="production").cors_allowed_origins == []


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.vercel.app",
        "http://portfolio-intelligence-bice.vercel.app",
        "http://localhost:3000",
        "https://localhost:3000",
        "https://127.0.0.1",
        "https://portfolio-intelligence-bice.vercel.app/",
        "https://portfolio-intelligence-bice.vercel.app/api",
    ],
)
def test_unsafe_production_cors_origins_are_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        production_settings(cors_allowed_origins=[origin])


# --- Database pooling and sync guards --------------------------------------------------


def test_transaction_pool_mode_disables_prepared_statements_and_client_pooling(migrated_database_url: str) -> None:
    session_mode = get_engine(Settings(_env_file=None, app_env="test", database_url=migrated_database_url))
    transaction_mode = get_engine(
        Settings(_env_file=None, app_env="test", database_url=migrated_database_url, database_pool_mode="transaction")
    )
    assert session_mode is not None and transaction_mode is not None
    assert not isinstance(session_mode.pool, NullPool)
    assert isinstance(transaction_mode.pool, NullPool)

    with transaction_mode.connect() as connection:
        for value in range(8):  # psycopg prepares a statement after 5 executions by default
            assert connection.execute(text("SELECT CAST(:value AS integer)"), {"value": value}).scalar() == value
        assert connection.connection.driver_connection.prepare_threshold is None
        assert connection.execute(text("SELECT count(*) FROM pg_prepared_statements")).scalar() == 0


@pytest.mark.parametrize("command", [["sync-listings"], ["sync-prices"], ["sync-prices", "--dry-run"]])
def test_sync_refuses_a_transaction_pooler_connection(
    command: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql://user:password@pooler.example:6543/postgres",
        database_pool_mode="transaction",
        indian_api_key="test-key-not-a-real-credential",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main(command) == 2
    assert "session-mode connection" in capsys.readouterr().err


def test_cli_database_errors_do_not_print_connection_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(
        _env_file=None, app_env="test", database_url="postgresql+psycopg://leaky_user:leaky_password@127.0.0.1:1/leaky_db"
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main(["status"]) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "OperationalError" in output
    for detail in ("leaky_user", "leaky_password", "leaky_db", "127.0.0.1"):
        assert detail not in output
