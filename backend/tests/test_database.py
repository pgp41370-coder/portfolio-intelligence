import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.database import normalize_database_url
from app.main import create_app


def test_db_health_reports_missing_configuration(client: TestClient) -> None:
    response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "database_not_configured",
            "message": "Database connection is not configured.",
        }
    }


def test_db_health_reports_unreachable_database_without_leaking_credentials() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://probe_user:probe-secret@127.0.0.1:1/probe_db",
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "probe-secret" not in response.text
    assert "probe_user" not in response.text


def test_settings_repr_hides_database_url() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://user:hunter2@db:5432/app")

    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings.model_dump())


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u@h:5432/db", "postgresql+psycopg://u@h:5432/db"),
        ("postgres://u@h:5432/db", "postgresql+psycopg://u@h:5432/db"),
        ("postgresql+psycopg://u@h:5432/db", "postgresql+psycopg://u@h:5432/db"),
    ],
)
def test_normalize_database_url_uses_psycopg_driver(url: str, expected: str) -> None:
    assert normalize_database_url(url) == expected


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL to run against a real PostgreSQL database",
)
def test_db_health_connects_to_real_database() -> None:
    settings = Settings(_env_file=None, database_url=os.environ["TEST_DATABASE_URL"])

    with TestClient(create_app(settings)) as client:
        response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
