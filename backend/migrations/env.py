"""Alembic environment. The database URL comes from DATABASE_URL, never from alembic.ini."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import Settings
from app.db.base import Base
from app.db.database import normalize_database_url
from app.market_data import models as market_data_models  # noqa: F401  (registers tables on Base.metadata)
from app.portfolios import models  # noqa: F401  (registers tables on Base.metadata)

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    # Tests pass the URL programmatically; everyone else uses DATABASE_URL.
    url = config.attributes.get("database_url")
    if url is None:
        settings = Settings()
        if settings.database_pool_mode == "transaction":
            raise RuntimeError(
                "Run migrations over a session-mode connection (Supabase session pooler or a direct "
                "connection), not DATABASE_POOL_MODE=transaction."
            )
        if settings.database_url is None:
            raise RuntimeError(
                "DATABASE_URL is not set. Copy backend/.env.example to backend/.env or export DATABASE_URL."
            )
        url = settings.database_url.get_secret_value()
    return normalize_database_url(url)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
