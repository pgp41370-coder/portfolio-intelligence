"""Version 1 of the public API.

Future finance modules (portfolios, analytics) get their own router module and
are mounted here, e.g. `api_router.include_router(portfolios.router, prefix="/portfolios")`.
"""

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.schemas.system import ApiInfoResponse

api_router = APIRouter(prefix="/api/v1")


@api_router.get("", response_model=ApiInfoResponse, tags=["meta"])
def api_info(settings: SettingsDep) -> ApiInfoResponse:
    return ApiInfoResponse(
        name=settings.app_name,
        version="v1",
        status="running",
        message=f"{settings.app_name} is running",
    )
