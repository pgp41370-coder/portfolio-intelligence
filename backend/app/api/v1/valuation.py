"""Portfolio valuation endpoint."""

import uuid
from typing import Any

from fastapi import APIRouter

from app.api.deps import NowDep, SessionDep, SettingsDep
from app.schemas.system import ErrorResponse
from app.valuation.schemas import PortfolioValuationRead
from app.valuation.service import value_portfolio

router = APIRouter(prefix="/portfolios", tags=["valuation"])

_ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorResponse} for code in (404, 422, 503)}


@router.get("/{portfolio_id}/valuation", response_model=PortfolioValuationRead, responses=_ERRORS)
def get_portfolio_valuation(
    portfolio_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
) -> PortfolioValuationRead:
    """Value a portfolio at the latest stored NSE end-of-day closing prices.

    Reads stored prices only; it never calls the market-data provider.
    """
    return value_portfolio(session, portfolio_id, settings=settings, now=now)
