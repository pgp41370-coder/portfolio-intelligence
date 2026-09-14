"""Portfolio API tests against a real PostgreSQL database (requires TEST_DATABASE_URL)."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

HDFC = {"symbol": "HDFCBANK", "exchange": "NSE", "quantity": 20, "average_buy_price": "1650"}
TCS = {"symbol": "TCS", "exchange": "NSE", "quantity": 10, "average_buy_price": "3200"}
RELIANCE = {"symbol": "RELIANCE", "exchange": "NSE", "quantity": 15, "average_buy_price": "1400"}

CountRows = Callable[[str], int]


def create_portfolio(client: TestClient, name: str = "Long-term", holdings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    response = client.post("/api/v1/portfolios", json={"name": name, "holdings": holdings or []})
    assert response.status_code == 201, response.text
    return response.json()


def error_messages(response: Any) -> list[str]:
    return [detail["message"] for detail in response.json()["error"].get("details", [])]


# --- Portfolio creation and retrieval ---------------------------------------


def test_create_portfolio_with_holdings(db_client: TestClient, count_rows: CountRows) -> None:
    body = create_portfolio(db_client, "Long-term", [TCS, HDFC])

    uuid.UUID(body["id"])
    assert body["name"] == "Long-term"
    assert [h["symbol"] for h in body["holdings"]] == ["HDFCBANK", "TCS"]
    assert body["holdings"][0]["exchange"] == "NSE"
    assert body["holdings"][0]["quantity"] == 20
    assert body["holdings"][0]["average_buy_price"] == "1650.00"
    assert body["total_invested_capital"] == "65000.00"
    assert count_rows("portfolios") == 1
    assert count_rows("holdings") == 2


def test_create_portfolio_without_holdings(db_client: TestClient) -> None:
    body = create_portfolio(db_client, "Empty")

    assert body["holdings"] == []
    assert body["total_invested_capital"] == "0.00"


def test_response_contains_only_user_data_and_invested_capital(db_client: TestClient) -> None:
    body = create_portfolio(db_client, holdings=[HDFC])

    assert set(body) == {"id", "name", "created_at", "updated_at", "holdings", "total_invested_capital"}
    assert set(body["holdings"][0]) == {
        "id", "symbol", "exchange", "quantity", "average_buy_price", "created_at", "updated_at",
    }


def test_retrieve_portfolio_with_holdings(db_client: TestClient) -> None:
    created = create_portfolio(db_client, "Core", [HDFC, TCS, RELIANCE])

    response = db_client.get(f"/api/v1/portfolios/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Core"
    assert [h["symbol"] for h in body["holdings"]] == ["HDFCBANK", "RELIANCE", "TCS"]
    assert body["total_invested_capital"] == "86000.00"


def test_portfolio_persists_across_app_instances(db_client: TestClient, migrated_database_url: str) -> None:
    from app.core.config import Settings
    from app.main import create_app

    created = create_portfolio(db_client, "Persistent", [HDFC])
    fresh_app = create_app(Settings(_env_file=None, database_url=migrated_database_url))

    with TestClient(fresh_app) as fresh_client:
        response = fresh_client.get(f"/api/v1/portfolios/{created['id']}")

    assert response.status_code == 200
    assert response.json()["holdings"][0]["symbol"] == "HDFCBANK"


def test_list_portfolios_newest_first_with_summary(db_client: TestClient) -> None:
    create_portfolio(db_client, "First", [HDFC])
    create_portfolio(db_client, "Second", [TCS, RELIANCE])

    response = db_client.get("/api/v1/portfolios")

    assert response.status_code == 200
    body = response.json()
    assert [p["name"] for p in body] == ["Second", "First"]
    assert body[0]["holding_count"] == 2
    assert body[0]["total_invested_capital"] == "53000.00"
    assert body[1]["total_invested_capital"] == "33000.00"


def test_list_portfolios_empty(db_client: TestClient) -> None:
    assert db_client.get("/api/v1/portfolios").json() == []


def test_nonexistent_portfolio_is_rejected(db_client: TestClient) -> None:
    response = db_client.get(f"/api/v1/portfolios/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "portfolio_not_found", "message": "Portfolio not found."}}


def test_malformed_portfolio_id_is_rejected(db_client: TestClient) -> None:
    assert db_client.get("/api/v1/portfolios/not-a-uuid").status_code == 422


# --- Holdings ----------------------------------------------------------------


def test_add_holding_and_retrieve_it(db_client: TestClient) -> None:
    portfolio = create_portfolio(db_client)

    response = db_client.post(f"/api/v1/portfolios/{portfolio['id']}/holdings", json=HDFC)

    assert response.status_code == 201
    holding = response.json()
    assert holding["symbol"] == "HDFCBANK"
    assert holding["average_buy_price"] == "1650.00"
    retrieved = db_client.get(f"/api/v1/portfolios/{portfolio['id']}").json()
    assert [h["id"] for h in retrieved["holdings"]] == [holding["id"]]
    assert retrieved["total_invested_capital"] == "33000.00"


def test_add_holding_normalizes_symbol_and_exchange(db_client: TestClient) -> None:
    portfolio = create_portfolio(db_client)

    response = db_client.post(
        f"/api/v1/portfolios/{portfolio['id']}/holdings",
        json={"symbol": "  m&m ", "exchange": "bse", "quantity": "5", "average_buy_price": 2900.25},
    )

    assert response.status_code == 201
    assert response.json()["symbol"] == "M&M"
    assert response.json()["exchange"] == "BSE"
    assert response.json()["average_buy_price"] == "2900.25"


def test_add_holding_preserves_four_decimal_places(db_client: TestClient) -> None:
    portfolio = create_portfolio(db_client)

    response = db_client.post(
        f"/api/v1/portfolios/{portfolio['id']}/holdings", json={**TCS, "quantity": 3, "average_buy_price": "3210.3333"}
    )

    assert response.json()["average_buy_price"] == "3210.3333"
    assert db_client.get(f"/api/v1/portfolios/{portfolio['id']}").json()["total_invested_capital"] == "9630.9999"


def test_add_holding_to_nonexistent_portfolio_is_rejected(db_client: TestClient, count_rows: CountRows) -> None:
    response = db_client.post(f"/api/v1/portfolios/{uuid.uuid4()}/holdings", json=HDFC)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "portfolio_not_found"
    assert count_rows("holdings") == 0


def test_duplicate_holding_is_rejected(db_client: TestClient, count_rows: CountRows) -> None:
    portfolio = create_portfolio(db_client, holdings=[HDFC])

    response = db_client.post(
        f"/api/v1/portfolios/{portfolio['id']}/holdings", json={**HDFC, "symbol": "hdfcbank", "quantity": 1}
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "duplicate_holding", "message": "HDFCBANK on NSE is already in this portfolio."}
    }
    assert count_rows("holdings") == 1


def test_same_symbol_on_other_exchange_is_allowed(db_client: TestClient) -> None:
    portfolio = create_portfolio(db_client, holdings=[HDFC])

    response = db_client.post(f"/api/v1/portfolios/{portfolio['id']}/holdings", json={**HDFC, "exchange": "BSE"})

    assert response.status_code == 201


def test_delete_holding(db_client: TestClient, count_rows: CountRows) -> None:
    portfolio = create_portfolio(db_client, holdings=[HDFC, TCS])
    holding_id = portfolio["holdings"][0]["id"]

    response = db_client.delete(f"/api/v1/portfolios/{portfolio['id']}/holdings/{holding_id}")

    assert response.status_code == 204
    assert response.content == b""
    remaining = db_client.get(f"/api/v1/portfolios/{portfolio['id']}").json()
    assert [h["symbol"] for h in remaining["holdings"]] == ["TCS"]
    assert remaining["total_invested_capital"] == "32000.00"
    assert count_rows("holdings") == 1


def test_nonexistent_holding_is_rejected(db_client: TestClient) -> None:
    portfolio = create_portfolio(db_client, holdings=[HDFC])

    response = db_client.delete(f"/api/v1/portfolios/{portfolio['id']}/holdings/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "holding_not_found"


def test_holding_from_another_portfolio_cannot_be_deleted(db_client: TestClient, count_rows: CountRows) -> None:
    first = create_portfolio(db_client, "First", [HDFC])
    second = create_portfolio(db_client, "Second", [TCS])

    response = db_client.delete(f"/api/v1/portfolios/{second['id']}/holdings/{first['holdings'][0]['id']}")

    assert response.status_code == 404
    assert count_rows("holdings") == 2


def test_delete_holding_in_nonexistent_portfolio_is_rejected(db_client: TestClient) -> None:
    response = db_client.delete(f"/api/v1/portfolios/{uuid.uuid4()}/holdings/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "portfolio_not_found"


# --- Validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "expected_message"),
    [
        ({"quantity": 0}, "Quantity must be greater than 0."),
        ({"quantity": -5}, "Quantity must be greater than 0."),
        ({"quantity": 2.5}, "Quantity must be a whole number of shares."),
        ({"average_buy_price": 0}, "Average buy price must be greater than 0."),
        ({"average_buy_price": "-1650"}, "Average buy price must be greater than 0."),
        ({"average_buy_price": "1650.12345"}, "Average buy price can have at most 4 decimal places."),
        ({"symbol": ""}, "Symbol is required."),
        ({"symbol": "   "}, "Symbol is required."),
        ({"symbol": "HDFC BANK"}, "Symbol must start with a letter or digit and contain only letters, digits, '&' or '-'."),
        ({"exchange": "NYSE"}, "Exchange must be NSE or BSE."),
        ({"current_price": "1700"}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_holding_is_rejected(
    db_client: TestClient, count_rows: CountRows, override: dict[str, Any], expected_message: str
) -> None:
    portfolio = create_portfolio(db_client)

    response = db_client.post(f"/api/v1/portfolios/{portfolio['id']}/holdings", json={**HDFC, **override})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert expected_message in error_messages(response)
    assert count_rows("holdings") == 0


def test_missing_holding_field_is_rejected(db_client: TestClient) -> None:
    portfolio = create_portfolio(db_client)
    payload = {key: value for key, value in HDFC.items() if key != "quantity"}

    response = db_client.post(f"/api/v1/portfolios/{portfolio['id']}/holdings", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize("name", ["", "    ", "x" * 101])
def test_invalid_portfolio_name_is_rejected(db_client: TestClient, count_rows: CountRows, name: str) -> None:
    response = db_client.post("/api/v1/portfolios", json={"name": name, "holdings": [HDFC]})

    assert response.status_code == 422
    assert count_rows("portfolios") == 0


def test_invalid_holding_in_new_portfolio_saves_nothing(db_client: TestClient, count_rows: CountRows) -> None:
    response = db_client.post(
        "/api/v1/portfolios", json={"name": "Mixed", "holdings": [HDFC, {**TCS, "quantity": 0}, RELIANCE]}
    )

    assert response.status_code == 422
    assert count_rows("portfolios") == 0
    assert count_rows("holdings") == 0


def test_duplicate_holdings_in_new_portfolio_save_nothing(db_client: TestClient, count_rows: CountRows) -> None:
    response = db_client.post("/api/v1/portfolios", json={"name": "Dupes", "holdings": [HDFC, TCS, HDFC]})

    assert response.status_code == 422
    assert "HDFCBANK on NSE is listed more than once" in error_messages(response)[0]
    assert count_rows("portfolios") == 0


def test_error_responses_do_not_expose_database_internals(db_client: TestClient) -> None:
    portfolio = create_portfolio(db_client, holdings=[HDFC])

    response = db_client.post(f"/api/v1/portfolios/{portfolio['id']}/holdings", json=HDFC)

    lowered = response.text.lower()
    for leak in ("psycopg", "uniqueviolation", "insert into", "sqlalchemy", "traceback", "postgresql"):
        assert leak not in lowered


# --- Database constraints (defence in depth behind the API validation) ------


@pytest.mark.parametrize(
    ("column", "value"),
    [("quantity", "0"), ("average_buy_price", "0"), ("exchange", "'NYS'"), ("symbol", "'hdfc bank'")],
)
def test_database_constraints_reject_invalid_rows(db_client: TestClient, db_engine: Engine, column: str, value: str) -> None:
    portfolio = create_portfolio(db_client)
    values = {"symbol": "'TCS'", "exchange": "'NSE'", "quantity": "1", "average_buy_price": "1", column: value}

    with pytest.raises(IntegrityError), db_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO holdings (portfolio_id, symbol, exchange, quantity, average_buy_price) "
                f"VALUES (:portfolio_id, {values['symbol']}, {values['exchange']}, {values['quantity']}, {values['average_buy_price']})"
            ),
            {"portfolio_id": portfolio["id"]},
        )


def test_deleting_portfolio_row_cascades_to_holdings(db_client: TestClient, db_engine: Engine, count_rows: CountRows) -> None:
    portfolio = create_portfolio(db_client, holdings=[HDFC, TCS])

    with db_engine.begin() as connection:
        connection.execute(text("DELETE FROM portfolios WHERE id = :id"), {"id": portfolio["id"]})

    assert count_rows("holdings") == 0


# --- Without a database ----------------------------------------------------------


def test_portfolio_endpoints_report_missing_database(client: TestClient) -> None:
    response = client.get("/api/v1/portfolios")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_not_configured"
