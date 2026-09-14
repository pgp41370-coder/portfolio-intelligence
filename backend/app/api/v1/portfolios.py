"""Portfolio endpoints: portfolios, holdings and CSV import."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Form, Response, UploadFile, status

from app.api.deps import SessionDep
from app.core.errors import AppError
from app.portfolios import service
from app.portfolios.calculations import total_invested_capital
from app.portfolios.csv_import import (
    ALLOWED_CSV_CONTENT_TYPES,
    MAX_CSV_BYTES,
    MAX_CSV_SIZE_LABEL,
    parse_holdings_csv,
)
from app.portfolios.models import Portfolio
from app.portfolios.rules import normalize_portfolio_name
from app.portfolios.schemas import (
    CsvIssueRead,
    CsvPreviewResponse,
    HoldingInput,
    HoldingRead,
    PortfolioCreate,
    PortfolioDetail,
    PortfolioSummary,
)
from app.schemas.system import ErrorResponse

router = APIRouter(prefix="/portfolios", tags=["portfolios"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (404, 409, 413, 415, 422, 503)
}


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PortfolioDetail, responses=_ERRORS)
def create_portfolio(payload: PortfolioCreate, session: SessionDep) -> PortfolioDetail:
    """Create a portfolio, optionally with its holdings, in one transaction."""
    return _to_detail(service.create_portfolio(session, payload))


@router.get("", response_model=list[PortfolioSummary], responses=_ERRORS)
def list_portfolios(session: SessionDep) -> list[PortfolioSummary]:
    return [
        PortfolioSummary(
            id=row.portfolio.id,
            name=row.portfolio.name,
            holding_count=row.holding_count,
            total_invested_capital=row.total_invested_capital,
            created_at=row.portfolio.created_at,
            updated_at=row.portfolio.updated_at,
        )
        for row in service.list_portfolios(session)
    ]


@router.post("/csv-preview", response_model=CsvPreviewResponse, responses=_ERRORS)
def preview_csv(file: UploadFile) -> CsvPreviewResponse:
    """Validate a holdings CSV and return the parsed rows. Nothing is saved."""
    result = parse_holdings_csv(_read_csv_upload(file))
    return CsvPreviewResponse(
        is_valid=result.is_valid,
        holding_count=len(result.holdings),
        holdings=result.holdings,
        total_invested_capital=total_invested_capital(result.holdings) if result.is_valid else None,
        errors=[CsvIssueRead(row=i.row, column=i.column, message=i.message) for i in result.errors],
    )


@router.post(
    "/csv-import", status_code=status.HTTP_201_CREATED, response_model=PortfolioDetail, responses=_ERRORS
)
def import_csv(
    name: Annotated[str, Form()],
    file: UploadFile,
    session: SessionDep,
) -> PortfolioDetail:
    """Create a portfolio from a holdings CSV. The file is validated again; any error saves nothing."""
    try:
        portfolio_name = normalize_portfolio_name(name)
    except ValueError as exc:
        raise AppError(
            422, "validation_error", str(exc), details=[{"loc": ["body", "name"], "message": str(exc)}]
        ) from None

    result = parse_holdings_csv(_read_csv_upload(file))
    if not result.is_valid:
        raise AppError(
            422,
            "invalid_csv",
            "The CSV file has errors. Nothing was saved.",
            details=[{"row": i.row, "column": i.column, "message": i.message} for i in result.errors],
        )

    payload = PortfolioCreate(name=portfolio_name, holdings=result.holdings)
    return _to_detail(service.create_portfolio(session, payload))


@router.get("/{portfolio_id}", response_model=PortfolioDetail, responses=_ERRORS)
def get_portfolio(portfolio_id: uuid.UUID, session: SessionDep) -> PortfolioDetail:
    return _to_detail(service.get_portfolio(session, portfolio_id))


@router.post(
    "/{portfolio_id}/holdings",
    status_code=status.HTTP_201_CREATED,
    response_model=HoldingRead,
    responses=_ERRORS,
)
def add_holding(portfolio_id: uuid.UUID, payload: HoldingInput, session: SessionDep) -> HoldingRead:
    return HoldingRead.model_validate(service.add_holding(session, portfolio_id, payload))


@router.delete(
    "/{portfolio_id}/holdings/{holding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
)
def delete_holding(portfolio_id: uuid.UUID, holding_id: uuid.UUID, session: SessionDep) -> Response:
    service.delete_holding(session, portfolio_id, holding_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _to_detail(portfolio: Portfolio) -> PortfolioDetail:
    holdings = [HoldingRead.model_validate(holding) for holding in portfolio.holdings]
    return PortfolioDetail(
        id=portfolio.id,
        name=portfolio.name,
        created_at=portfolio.created_at,
        updated_at=portfolio.updated_at,
        holdings=holdings,
        total_invested_capital=total_invested_capital(holdings),
    )


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
