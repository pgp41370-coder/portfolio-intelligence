"""Version 1 of the public API.

Each finance module gets its own router module and is mounted here.
"""

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.api.v1 import portfolios
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


api_router.include_router(portfolios.router)
