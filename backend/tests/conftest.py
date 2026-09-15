import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.database import normalize_database_url
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALL_TABLES = ("daily_prices", "market_data_sync_runs", "listings", "holdings", "portfolios")


@pytest.fixture
def settings() -> Settings:
    # Ignore any local .env so tests are deterministic.
    return Settings(_env_file=None, app_env="test", database_url=None)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Database fixtures. They run only when TEST_DATABASE_URL is set, and only
# against a database whose name ends in "_test", because they reset its schema.
# ---------------------------------------------------------------------------


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def test_database_url() -> str:
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("set TEST_DATABASE_URL to run database tests")
    url = normalize_database_url(raw_url)
    if not (make_url(url).database or "").endswith("_test"):
        pytest.exit(
            "TEST_DATABASE_URL must name a database ending in '_test'; refusing to reset any other database.",
            returncode=2,
        )
    return url


@pytest.fixture(scope="session")
def migrated_database_url(test_database_url: str) -> str:
    """Rebuild the schema from scratch with the real migrations."""
    config = alembic_config(test_database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return test_database_url


@pytest.fixture(scope="session")
def db_engine(migrated_database_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_database(db_engine: Engine) -> None:
    with db_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(ALL_TABLES)}"))


@pytest.fixture
def db_session_factory(db_engine: Engine, clean_database: None) -> sessionmaker[Session]:
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
def db_client(migrated_database_url: str, clean_database: None) -> Iterator[TestClient]:
    settings = Settings(_env_file=None, app_env="test", database_url=migrated_database_url)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def count_rows(db_engine: Engine) -> Callable[[str], int]:
    def _count(table: str) -> int:
        assert table in ALL_TABLES
        with db_engine.connect() as connection:
            return int(connection.scalar(text(f"SELECT count(*) FROM {table}")) or 0)

    return _count
