"""Database engine management and connectivity checks.

No tables are defined yet. This module turns DATABASE_URL into a SQLAlchemy
engine and verifies that the database answers a trivial query.
"""

import logging
from enum import StrEnum
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings

logger = logging.getLogger(__name__)

_PLAIN_SCHEMES = ("postgres://", "postgresql://")
_PSYCOPG_SCHEME = "postgresql+psycopg://"


class DatabaseStatus(StrEnum):
    CONNECTED = "connected"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"


def normalize_database_url(url: str) -> str:
    """Use the psycopg 3 driver for plain PostgreSQL URLs, such as those issued by Supabase."""
    for scheme in _PLAIN_SCHEMES:
        if url.startswith(scheme):
            return _PSYCOPG_SCHEME + url.removeprefix(scheme)
    return url


@lru_cache(maxsize=4)
def _create_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


def get_engine(settings: Settings) -> Engine | None:
    if settings.database_url is None:
        return None
    return _create_engine(normalize_database_url(settings.database_url.get_secret_value()))


def check_database(settings: Settings) -> DatabaseStatus:
    """Report whether the configured database answers `SELECT 1`."""
    if settings.database_url is None:
        return DatabaseStatus.NOT_CONFIGURED
    try:
        engine = get_engine(settings)
        assert engine is not None
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Log only the exception type: driver messages can include host and user names.
        logger.warning("Database connectivity check failed: %s", type(exc).__name__)
        return DatabaseStatus.UNAVAILABLE
    return DatabaseStatus.CONNECTED
