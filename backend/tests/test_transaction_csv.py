"""Transaction CSV parsing, validation and atomic import."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from app.transactions.csv_import import parse_transactions_csv
from test_performance_api import MakeClient, SessionFactory, seed  # noqa: F401
from test_valuation_api import add_listing, add_price, create_portfolio, make_client  # noqa: F401

MON, TUE, WED = date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)
LATEST = date(2026, 9, 18)
WEDNESDAY_EVENING = datetime(2026, 9, 16, 13, 0, tzinfo=UTC)

HEADER = "trade_date,symbol,exchange,type,quantity,price,fees,reference"


def csv_bytes(*rows: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode()


def parse(*rows: str, header: str = HEADER, existing=None, latest: date = LATEST):
    return parse_transactions_csv(
        csv_bytes(*rows, header=header), latest_session=latest, existing=existing or [], existing_count=len(existing or [])
    )


def upload(client: TestClient, portfolio_id: str, content: bytes, *, action: str = "csv-preview", name: str = "t.csv"):
    return client.post(
        f"/api/v1/portfolios/{portfolio_id}/transactions/{action}",
        files={"file": (name, content, "text/csv")},
    )


# --- Parsing ------------------------------------------------------------------------------


def test_a_valid_file_parses_every_row() -> None:
    result = parse(
        "2026-09-14,RELIANCE,NSE,BUY,10,1234.50,23.60,ORD-1",
        "2026-09-15,TCS,NSE,BUY,5,3200,10,",
    )

    assert result.is_valid, result.errors
    assert [item.symbol for item in result.transactions] == ["RELIANCE", "TCS"]
    assert result.transactions[0].price == Decimal("1234.5000")
    assert result.transactions[0].fees == Decimal("23.6000")
    assert result.transactions[0].reference == "ORD-1"
    assert result.transactions[1].reference is None


def test_optional_columns_may_be_omitted() -> None:
    result = parse(
        "2026-09-14,RELIANCE,NSE,BUY,10,1234.50",
        header="trade_date,symbol,exchange,type,quantity,price",
    )

    assert result.is_valid, result.errors
    assert result.transactions[0].fees == Decimal(0)


def test_column_order_and_case_are_free() -> None:
    result = parse(
        "BUY,NSE,10,RELIANCE,1234.50,2026-09-14",
        header="Type,Exchange,Quantity,Symbol,Price,Trade_Date",
    )

    assert result.is_valid, result.errors
    assert result.transactions[0].symbol == "RELIANCE"


# --- Row-level validation -----------------------------------------------------------------


def test_missing_columns_are_named() -> None:
    result = parse("2026-09-14,RELIANCE,NSE", header="trade_date,symbol,exchange")

    assert not result.is_valid
    assert "Missing columns" in result.errors[0].message
    assert "type" in result.errors[0].message and "quantity" in result.errors[0].message


def test_unsupported_columns_are_rejected() -> None:
    result = parse(
        "2026-09-14,RELIANCE,NSE,BUY,10,1234.50,ignore-me",
        header="trade_date,symbol,exchange,type,quantity,price,broker_notes",
    )

    assert not result.is_valid
    assert "Unsupported column" in result.errors[0].message


def test_each_invalid_value_is_reported_with_its_row_and_column() -> None:
    result = parse(
        "not-a-date,RELIANCE,NSE,BUY,10,1234.50,0,",
        "2026-09-14,RELIANCE,NSE,GIFT,10,1234.50,0,",
        "2026-09-14,RELIANCE,NSE,BUY,0,1234.50,0,",
        "2026-09-14,RELIANCE,NSE,BUY,10,-5,0,",
        "2026-09-14,RELIANCE,NSE,BUY,1.5,10,0,",
        "2026-09-14,RELIANCE,NSE,BUY,10,10,-1,",
    )

    assert not result.is_valid
    by_row = {issue.row: issue for issue in result.errors}
    assert "date in YYYY-MM-DD" in by_row[2].message and by_row[2].column == "trade_date"
    assert "BUY or SELL" in by_row[3].message and by_row[3].column == "type"
    assert "greater than 0" in by_row[4].message and by_row[4].column == "quantity"
    assert "greater than 0" in by_row[5].message and by_row[5].column == "price"
    assert "whole number" in by_row[6].message
    assert "Fees cannot be negative" in by_row[7].message


def test_a_future_trade_date_is_rejected() -> None:
    result = parse("2026-09-21,RELIANCE,NSE,BUY,10,1234.50,0,")

    assert not result.is_valid
    assert "after the latest completed NSE session" in result.errors[0].message
    assert result.errors[0].row == 2


def test_wrong_number_of_values_is_reported() -> None:
    result = parse("2026-09-14,RELIANCE,NSE,BUY,10")

    assert not result.is_valid
    assert "missing or extra commas" in result.errors[0].message


def test_malformed_and_empty_files_are_rejected() -> None:
    assert not parse_transactions_csv(b"", latest_session=LATEST).is_valid
    assert not parse_transactions_csv(b"\xff\xfe\x00bad", latest_session=LATEST).is_valid
    header_only = parse_transactions_csv(csv_bytes(), latest_session=LATEST)
    assert not header_only.is_valid
    assert "no transactions" in header_only.errors[0].message


# --- Duplicates and ledger consistency -------------------------------------------------------


def test_duplicate_rows_in_the_file_are_rejected() -> None:
    result = parse(
        "2026-09-14,RELIANCE,NSE,BUY,10,1234.50,0,",
        "2026-09-14,RELIANCE,NSE,BUY,10,1234.50,0,",
    )

    assert not result.is_valid
    assert "Duplicate transaction" in result.errors[0].message
    assert "row 2" in result.errors[0].message


def test_a_row_duplicating_a_stored_transaction_is_rejected() -> None:
    result = parse(
        "2026-09-14,RELIANCE,NSE,BUY,10,1234.50,0,",
        existing=[(MON, "RELIANCE", "NSE", "BUY", 10)],
    )

    assert not result.is_valid
    assert "already recorded for this portfolio" in result.errors[0].message


def test_selling_more_than_the_file_bought_is_rejected_with_the_available_quantity() -> None:
    result = parse(
        "2026-09-14,INFY,NSE,BUY,60,1500,0,",
        "2026-09-15,INFY,NSE,SELL,100,1600,0,",
    )

    assert not result.is_valid
    issue = result.errors[0]
    assert issue.row == 3 and issue.column == "quantity"
    assert "selling 100 INFY" in issue.message and "only 60 held" in issue.message


def test_a_sale_is_checked_against_the_stored_ledger_too() -> None:
    held = [(MON, "INFY", "NSE", "BUY", 60)]

    assert parse("2026-09-15,INFY,NSE,SELL,60,1600,0,", existing=held).is_valid
    too_many = parse("2026-09-15,INFY,NSE,SELL,61,1600,0,", existing=held)
    assert not too_many.is_valid and "only 60 held" in too_many.errors[0].message


def test_a_partial_sell_leaves_the_rest_available() -> None:
    result = parse(
        "2026-09-14,INFY,NSE,BUY,60,1500,0,",
        "2026-09-15,INFY,NSE,SELL,20,1600,0,",
        "2026-09-16,INFY,NSE,SELL,40,1700,0,",
    )

    assert result.is_valid, result.errors


def test_rows_out_of_date_order_are_rejected() -> None:
    result = parse(
        "2026-09-16,RELIANCE,NSE,BUY,10,1234.50,0,",
        "2026-09-14,TCS,NSE,BUY,10,3200,0,",
    )

    assert not result.is_valid
    assert "date order" in result.errors[0].message


def test_every_bad_row_is_reported_not_just_the_first() -> None:
    result = parse(
        "2026-09-14,RELIANCE,NSE,BUY,10,1234.50,0,",
        "bad-date,TCS,NSE,BUY,10,3200,0,",
        "2026-09-15,INFY,NSE,SELL,10,1600,0,",
    )

    rows = sorted(issue.row for issue in result.errors if issue.row)
    assert rows == [3, 4]  # the bad date and the impossible sale


# --- Through the API -------------------------------------------------------------------------


def test_preview_reports_what_would_be_imported_and_saves_nothing(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client)

    response = upload(
        client,
        portfolio_id,
        csv_bytes("2026-09-14,RELIANCE,NSE,BUY,10,100,25,ORD-1", "2026-09-15,TCS,NSE,BUY,5,200,10,"),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_valid"] is True
    assert body["transaction_count"] == 2
    assert body["net_cash_flow"] == "2035.00"  # 1,000 + 25 + 1,000 + 10
    assert client.get(f"/api/v1/portfolios/{portfolio_id}/transactions").json()["count"] == 0


def test_import_is_atomic_when_any_row_fails(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client)

    response = upload(
        client,
        portfolio_id,
        csv_bytes("2026-09-14,RELIANCE,NSE,BUY,10,100,0,", "2026-09-15,INFY,NSE,SELL,10,100,0,"),
        action="csv-import",
    )

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "invalid_csv"
    assert any("exceeds available quantity" in detail["message"] for detail in body["details"])
    # The valid first row is not imported either.
    assert client.get(f"/api/v1/portfolios/{portfolio_id}/transactions").json()["count"] == 0


def test_a_valid_import_stores_every_row(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client)

    response = upload(
        client,
        portfolio_id,
        csv_bytes("2026-09-14,RELIANCE,NSE,BUY,10,100,25,ORD-1", "2026-09-15,RELIANCE,NSE,SELL,4,110,5,ORD-2"),
        action="csv-import",
    )

    assert response.status_code == 201, response.text
    stored = client.get(f"/api/v1/portfolios/{portfolio_id}/transactions").json()
    assert stored["count"] == 2
    assert [row["kind"] for row in stored["transactions"]] == ["BUY", "SELL"]
    assert stored["transactions"][0]["reference"] == "ORD-1"


def test_import_refuses_a_file_that_conflicts_with_the_stored_ledger(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client)
    upload(client, portfolio_id, csv_bytes("2026-09-14,RELIANCE,NSE,BUY,10,100,0,"), action="csv-import")

    response = upload(
        client, portfolio_id, csv_bytes("2026-09-15,RELIANCE,NSE,SELL,11,110,0,"), action="csv-import"
    )

    assert response.status_code == 422
    assert client.get(f"/api/v1/portfolios/{portfolio_id}/transactions").json()["count"] == 1


def test_uploads_are_size_and_type_limited(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client)

    wrong_type = upload(client, portfolio_id, b"trade_date\n", name="ledger.txt")
    oversized = upload(client, portfolio_id, b"x" * (1024 * 1024 + 1))

    assert wrong_type.status_code == 415
    assert oversized.status_code == 413


def test_csv_upload_requires_a_known_portfolio(make_client: MakeClient, db_session_factory: SessionFactory) -> None:
    client = make_client(now=WEDNESDAY_EVENING)

    response = upload(client, "00000000-0000-0000-0000-000000000000", csv_bytes("2026-09-14,RELIANCE,NSE,BUY,1,1,0,"))

    assert response.status_code == 404


def test_csv_cells_are_never_evaluated_as_formulas(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """A spreadsheet formula is just an invalid symbol here, never something to execute."""
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client)

    response = upload(
        client, portfolio_id, csv_bytes('2026-09-14,=cmd|\' /c calc\'!A1,NSE,BUY,10,100,0,')
    )

    body = response.json()
    assert body["is_valid"] is False
    assert any(issue["column"] == "symbol" for issue in body["errors"])


def test_csv_import_is_blocked_in_production(migrated_database_url: str) -> None:
    from app.core.config import Settings
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url=migrated_database_url,
        cors_allowed_origins=["https://portfolio-intelligence-bice.vercel.app"],
    )
    with TestClient(create_app(settings)) as client:
        preview = upload(client, "00000000-0000-0000-0000-000000000000", csv_bytes("2026-09-14,X,NSE,BUY,1,1,0,"))
        imported = upload(
            client, "00000000-0000-0000-0000-000000000000", csv_bytes("2026-09-14,X,NSE,BUY,1,1,0,"), action="csv-import"
        )

    assert preview.status_code == 403 and preview.json()["error"]["code"] == "read_only_demo"
    assert imported.status_code == 403
