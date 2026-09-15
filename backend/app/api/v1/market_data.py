"""Market-data status endpoint. Operational information only; never credentials."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import NowDep, SessionDep, SettingsDep
from app.market_data.schemas import MarketDataStatusRead
from app.market_data.service import get_status
from app.schemas.system import ErrorResponse

router = APIRouter(prefix="/market-data", tags=["market data"])


@router.get(
    "/status",
    response_model=MarketDataStatusRead,
    responses={503: {"model": ErrorResponse}},
)
def market_data_status(session: SessionDep, settings: SettingsDep, now: NowDep) -> MarketDataStatusRead:
    return get_status(session, settings, now)


__all__: list[Any] = ["router"]
