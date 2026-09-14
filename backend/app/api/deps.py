"""Shared FastAPI dependencies."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.database import get_session_factory


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def get_db_session(settings: SettingsDep) -> Iterator[Session]:
    session_factory = get_session_factory(settings)
    if session_factory is None:
        raise AppError(503, "database_not_configured", "Database connection is not configured.")
    # Closing the session rolls back anything that was not explicitly committed.
    with session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db_session)]
