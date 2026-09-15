"""Database engine and session management, plus a connectivity check.

The schema itself is managed by Alembic migrations (see backend/migrations).
"""

import logging
from enum import StrEnum
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

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
def _create_engine(url: str, pool_mode: str = "session") -> Engine:
    if pool_mode == "transaction":
        # A transaction-mode pooler (e.g. Supabase port 6543) hands each transaction to any server
        # connection, so psycopg's prepared statements cannot be reused and connection pooling is
        # left to the pooler. Each checkout opens a connection to the pooler, not to PostgreSQL.
        return create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5, "prepare_threshold": None})
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


@lru_cache(maxsize=4)
def _create_session_factory(url: str, pool_mode: str = "session") -> sessionmaker[Session]:
    return sessionmaker(bind=_create_engine(url, pool_mode), expire_on_commit=False)


def _database_url(settings: Settings) -> str | None:
    if settings.database_url is None:
        return None
    return normalize_database_url(settings.database_url.get_secret_value())


def get_engine(settings: Settings) -> Engine | None:
    url = _database_url(settings)
    return None if url is None else _create_engine(url, settings.database_pool_mode)


def get_session_factory(settings: Settings) -> sessionmaker[Session] | None:
    url = _database_url(settings)
    return None if url is None else _create_session_factory(url, settings.database_pool_mode)


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
