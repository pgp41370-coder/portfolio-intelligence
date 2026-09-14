"""Migration tests: the schema is built from scratch by Alembic and matches the ORM models."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect

from app.db.base import Base
from app.portfolios import models  # noqa: F401  (registers tables)


def test_fresh_database_has_portfolio_tables(db_engine: Engine) -> None:
    inspector = inspect(db_engine)

    assert {"portfolios", "holdings", "alembic_version"} <= set(inspector.get_table_names())
    assert {c["name"] for c in inspector.get_columns("holdings")} == {
        "id", "portfolio_id", "symbol", "exchange", "quantity", "average_buy_price", "created_at", "updated_at",
    }


def test_holdings_constraints_exist(db_engine: Engine) -> None:
    inspector = inspect(db_engine)

    checks = {c["name"] for c in inspector.get_check_constraints("holdings")}
    assert checks == {
        "ck_holdings_quantity_positive",
        "ck_holdings_average_buy_price_positive",
        "ck_holdings_exchange_valid",
        "ck_holdings_symbol_format",
    }
    [foreign_key] = inspector.get_foreign_keys("holdings")
    assert foreign_key["referred_table"] == "portfolios"
    assert foreign_key["options"].get("ondelete") == "CASCADE"
    uniques = {u["name"]: u["column_names"] for u in inspector.get_unique_constraints("holdings")}
    assert uniques == {"uq_holdings_portfolio_id_symbol_exchange": ["portfolio_id", "symbol", "exchange"]}


def test_migration_matches_models(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []
