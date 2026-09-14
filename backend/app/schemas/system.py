"""Response models for system endpoints and errors."""

from typing import Any, Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]


class DatabaseHealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["connected"]


class ApiInfoResponse(BaseModel):
    name: str
    version: str
    status: Literal["running"]
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
