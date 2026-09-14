"""CSV preview and import endpoint tests."""

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.portfolios.csv_import import MAX_CSV_BYTES

CountRows = Callable[[str], int]

VALID_CSV = b"""symbol,exchange,quantity,average_buy_price
HDFCBANK,NSE,20,1650
TCS,NSE,10,3200
RELIANCE,NSE,15,1400
"""
INVALID_CSV = b"""symbol,exchange,quantity,average_buy_price
HDFCBANK,NSE,20,1650
TCS,NSE,0,3200
RELIANCE,NSE,15,1400
HDFCBANK,NSE,5,1700
"""


def upload(content: bytes, filename: str = "holdings.csv", content_type: str = "text/csv") -> dict[str, tuple[str, bytes, str]]:
    return {"file": (filename, content, content_type)}


# --- Preview (validates only; needs no database) -----------------------------


def test_preview_valid_csv_returns_rows_and_total(client: TestClient) -> None:
    response = client.post("/api/v1/portfolios/csv-preview", files=upload(VALID_CSV))

    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is True
    assert body["errors"] == []
    assert body["holding_count"] == 3
    assert body["holdings"][0] == {"symbol": "HDFCBANK", "exchange": "NSE", "quantity": 20, "average_buy_price": "1650.00"}
    assert body["total_invested_capital"] == "86000.00"


def test_preview_invalid_csv_reports_every_problem(client: TestClient) -> None:
    response = client.post("/api/v1/portfolios/csv-preview", files=upload(INVALID_CSV))

    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is False
    assert body["total_invested_capital"] is None
    assert [(e["row"], e["column"]) for e in body["errors"]] == [(3, "quantity"), (5, "symbol")]
    assert "Duplicate holding" in body["errors"][1]["message"]


def test_preview_missing_header_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/portfolios/csv-preview", files=upload(b"symbol,quantity\nTCS,1\n"))

    assert response.json()["is_valid"] is False
    assert "Missing required column(s): exchange, average_buy_price" in response.json()["errors"][0]["message"]


def test_non_csv_extension_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/portfolios/csv-preview", files=upload(VALID_CSV, filename="holdings.xlsx"))

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_non_csv_content_type_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/portfolios/csv-preview", files=upload(VALID_CSV, content_type="image/png"))

    assert response.status_code == 415


def test_file_just_over_limit_is_rejected(client: TestClient) -> None:
    content = VALID_CSV + b"#" * (MAX_CSV_BYTES + 1 - len(VALID_CSV))

    response = client.post("/api/v1/portfolios/csv-preview", files=upload(content))

    assert response.status_code == 413
    assert response.json()["error"] == {"code": "file_too_large", "message": "CSV files must be 1 MB or smaller."}


def test_very_large_upload_is_rejected_before_parsing(client: TestClient) -> None:
    response = client.post("/api/v1/portfolios/csv-preview", files=upload(b"x" * (3 * MAX_CSV_BYTES)))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


# --- Import (validates again, then saves atomically) ----------------------------


def test_import_valid_csv_creates_portfolio(db_client: TestClient, count_rows: CountRows) -> None:
    response = db_client.post("/api/v1/portfolios/csv-import", data={"name": "From CSV"}, files=upload(VALID_CSV))

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "From CSV"
    assert [h["symbol"] for h in body["holdings"]] == ["HDFCBANK", "RELIANCE", "TCS"]
    assert body["total_invested_capital"] == "86000.00"
    assert count_rows("portfolios") == 1
    assert count_rows("holdings") == 3
    assert db_client.get(f"/api/v1/portfolios/{body['id']}").status_code == 200


def test_invalid_csv_does_not_partially_save(db_client: TestClient, count_rows: CountRows) -> None:
    response = db_client.post("/api/v1/portfolios/csv-import", data={"name": "Broken"}, files=upload(INVALID_CSV))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_csv"
    assert error["message"] == "The CSV file has errors. Nothing was saved."
    assert [(d["row"], d["column"]) for d in error["details"]] == [(3, "quantity"), (5, "symbol")]
    assert count_rows("portfolios") == 0
    assert count_rows("holdings") == 0


def test_malformed_csv_import_saves_nothing(db_client: TestClient, count_rows: CountRows) -> None:
    content = b'symbol,exchange,quantity,average_buy_price\nHDFCBANK,NSE,20,1650\n"TCS,NSE,10,3200\n'

    response = db_client.post("/api/v1/portfolios/csv-import", data={"name": "Malformed"}, files=upload(content))

    assert response.status_code == 422
    assert count_rows("portfolios") == 0


def test_import_with_blank_name_saves_nothing(db_client: TestClient, count_rows: CountRows) -> None:
    response = db_client.post("/api/v1/portfolios/csv-import", data={"name": "   "}, files=upload(VALID_CSV))

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Portfolio name is required."
    assert count_rows("portfolios") == 0


def test_import_rejects_wrong_file_type_and_saves_nothing(db_client: TestClient, count_rows: CountRows) -> None:
    response = db_client.post(
        "/api/v1/portfolios/csv-import", data={"name": "Wrong"}, files=upload(VALID_CSV, filename="holdings.txt")
    )

    assert response.status_code == 415
    assert count_rows("portfolios") == 0
