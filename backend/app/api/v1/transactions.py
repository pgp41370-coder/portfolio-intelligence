"""Transaction ledger endpoints.

Reads are always available. Writes go through the same protection as every other write in the
application: the production middleware rejects non-GET requests before the body is read, so the
public demo stays read-only.
"""

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Body, Response, UploadFile, status

from app.api.deps import NowDep, SessionDep, SettingsDep
from app.core.errors import AppError
from app.market_data.calendar import latest_expected_session
from app.portfolios.schemas import CsvIssueRead
from app.portfolios.service import get_portfolio
from app.schemas.system import ErrorResponse
from app.transactions import service
from app.transactions.csv_import import (
    ALLOWED_CSV_CONTENT_TYPES,
    MAX_CSV_BYTES,
    MAX_CSV_SIZE_LABEL,
    parse_transactions_csv,
)
from app.transactions.schemas import (
    TransactionCsvPreviewRead,
    TransactionInput,
    TransactionListRead,
    TransactionRead,
)

router = APIRouter(prefix="/portfolios/{portfolio_id}/transactions", tags=["transactions"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 413, 415, 422, 503)
}


@router.get("", response_model=TransactionListRead, responses=_ERRORS)
def list_transactions(portfolio_id: uuid.UUID, session: SessionDep) -> TransactionListRead:
    """Every recorded transaction, oldest first."""
    portfolio = get_portfolio(session, portfolio_id)
    rows = service.list_transactions(session, portfolio_id)
    return TransactionListRead(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        count=len(rows),
        transactions=[TransactionRead.model_validate(row) for row in rows],
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=list[TransactionRead], responses=_ERRORS)
def add_transactions(
    portfolio_id: uuid.UUID,
    payload: Annotated[list[TransactionInput], Body(min_length=1, max_length=500)],
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
) -> list[TransactionRead]:
    """Append transactions, rejecting future trade dates and any sell that would oversell."""
    latest = latest_expected_session(now, settings.trading_calendar)
    rows = service.add_transactions(session, portfolio_id, payload, latest_session=latest)
    return [TransactionRead.model_validate(row) for row in rows]


@router.post("/csv-preview", response_model=TransactionCsvPreviewRead, responses=_ERRORS)
def preview_transactions_csv(
    portfolio_id: uuid.UUID,
    file: UploadFile,
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
) -> TransactionCsvPreviewRead:
    """Validate a transactions CSV against this portfolio's ledger. Nothing is saved.

    Sales are checked against the position the stored ledger and the earlier rows actually
    produce, so "sell exceeds available quantity" means what it says.
    """
    result = _parse_upload(portfolio_id, file, session, settings, now)
    return TransactionCsvPreviewRead(
        is_valid=result.is_valid,
        transaction_count=len(result.transactions),
        transactions=result.transactions,
        net_cash_flow=_net_cash_flow(result.transactions) if result.is_valid else None,
        errors=[CsvIssueRead(row=i.row, column=i.column, message=i.message) for i in result.errors],
    )


@router.post("/csv-import", status_code=status.HTTP_201_CREATED, response_model=list[TransactionRead], responses=_ERRORS)
def import_transactions_csv(
    portfolio_id: uuid.UUID,
    file: UploadFile,
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
) -> list[TransactionRead]:
    """Import a transactions CSV atomically: any error and nothing at all is saved."""
    result = _parse_upload(portfolio_id, file, session, settings, now)
    if not result.is_valid:
        raise AppError(
            422,
            "invalid_csv",
            "The CSV file has errors. Nothing was saved.",
            details=[{"row": i.row, "column": i.column, "message": i.message} for i in result.errors],
        )
    latest = latest_expected_session(now, settings.trading_calendar)
    rows = service.add_transactions(session, portfolio_id, result.transactions, latest_session=latest)
    return [TransactionRead.model_validate(row) for row in rows]


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS)
def delete_transaction(portfolio_id: uuid.UUID, transaction_id: uuid.UUID, session: SessionDep) -> Response:
    """Remove one transaction, refusing if the remaining ledger would be oversold."""
    service.delete_transaction(session, portfolio_id, transaction_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _parse_upload(
    portfolio_id: uuid.UUID, file: UploadFile, session: SessionDep, settings: SettingsDep, now: NowDep
):
    get_portfolio(session, portfolio_id)  # 404 before anything is read
    existing = [
        (row.trade_date, row.symbol, row.exchange, row.kind, row.quantity)
        for row in service.list_transactions(session, portfolio_id)
    ]
    return parse_transactions_csv(
        _read_csv_upload(file),
        latest_session=latest_expected_session(now, settings.trading_calendar),
        existing=existing,
        existing_count=len(existing),
    )


def _net_cash_flow(transactions: list[TransactionInput]) -> Decimal:
    """What the file would move in and out, so the preview can state it before importing."""
    total = Decimal(0)
    for item in transactions:
        gross = Decimal(item.quantity) * item.price
        total += gross + item.fees if item.kind == "BUY" else -(gross - item.fees)
    return total


def _read_csv_upload(file: UploadFile) -> bytes:
    """Read the uploaded file from the request's temporary storage; it is never persisted."""
    if not (file.filename or "").strip().lower().endswith(".csv"):
        raise AppError(415, "unsupported_file_type", "Upload a .csv file.")
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CSV_CONTENT_TYPES:
        raise AppError(415, "unsupported_file_type", "Upload a .csv file.")
    content = file.file.read(MAX_CSV_BYTES + 1)
    if len(content) > MAX_CSV_BYTES:
        raise AppError(413, "file_too_large", f"CSV files must be {MAX_CSV_SIZE_LABEL} or smaller.")
    return content
