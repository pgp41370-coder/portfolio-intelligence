"""Liveness and database connectivity checks."""

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.core.errors import AppError
from app.db.database import DatabaseStatus, check_database
from app.schemas.system import DatabaseHealthResponse, ErrorResponse, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/health/db",
    response_model=DatabaseHealthResponse,
    responses={503: {"model": ErrorResponse}},
)
def database_health(settings: SettingsDep) -> DatabaseHealthResponse:
    status = check_database(settings)
    if status is DatabaseStatus.NOT_CONFIGURED:
        raise AppError(503, "database_not_configured", "Database connection is not configured.")
    if status is DatabaseStatus.UNAVAILABLE:
        raise AppError(503, "database_unavailable", "Database is not reachable.")
    return DatabaseHealthResponse(status="ok", database="connected")
