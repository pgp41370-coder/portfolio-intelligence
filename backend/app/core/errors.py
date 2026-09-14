"""Consistent JSON error responses.

Every error leaves the API in the same shape:

    {"error": {"code": "not_found", "message": "Not Found"}}

Validation errors add a `details` list describing each problem.
"""

import logging
from collections.abc import Sequence
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.system import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """An expected error with a stable, machine-readable code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details))
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body, exclude_none=True),
        headers=headers,
    )


def _code_for_status(status_code: int) -> str:
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        return "http_error"
    return phrase.lower().replace(" ", "_").replace("-", "_")


def _validation_details(errors: Sequence[Any]) -> list[dict[str, Any]]:
    details = []
    for error in errors:
        message = error.get("msg", "Invalid value.")
        context = error.get("ctx") or {}
        # Our own validators raise ValueError with a user-facing message; show it without Pydantic's prefix.
        if error.get("type") == "value_error" and "error" in context:
            message = str(context["error"])
        details.append({"loc": list(error.get("loc", ())), "message": message})
    return details


async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, details=exc.details)


async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(
        exc.status_code,
        _code_for_status(exc.status_code),
        message,
        headers=exc.headers,
    )


async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(
        422,
        "validation_error",
        "The request is invalid.",
        details=_validation_details(exc.errors()),
    )


async def _handle_database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    # Log only the exception type: driver messages can include host and user names.
    logger.warning(
        "Database unavailable during %s %s: %s", request.method, request.url.path, type(exc).__name__
    )
    return error_response(503, "database_unavailable", "Database is not reachable.")


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Log the full traceback server-side; never return internal details to the client.
    logger.error("Unhandled error during %s %s", request.method, request.url.path, exc_info=exc)
    return error_response(500, "internal_server_error", "An unexpected error occurred.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(OperationalError, _handle_database_unavailable)
    app.add_exception_handler(Exception, _handle_unexpected_error)
