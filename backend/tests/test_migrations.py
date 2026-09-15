"""Migration tests: the schema is built from scratch by Alembic and matches the ORM models."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from app.db.base import Base
from app.market_data import models as market_data_models  # noqa: F401  (registers tables)
from app.portfolios import models  # noqa: F401  (registers tables)


def test_fresh_database_has_all_tables(db_engine: Engine) -> None:
    tables = set(inspect(db_engine).get_table_names())

    assert {"portfolios", "holdings", "listings", "daily_prices", "market_data_sync_runs", "alembic_version"} <= tables


def test_m2_tables_are_unchanged_by_market_data_migration(db_engine: Engine) -> None:
    inspector = inspect(db_engine)

    assert {c["name"] for c in inspector.get_columns("portfolios")} == {"id", "name", "created_at", "updated_at"}
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


def test_market_data_constraints_exist(db_engine: Engine) -> None:
    inspector = inspect(db_engine)

    listing_uniques = {u["name"]: u["column_names"] for u in inspector.get_unique_constraints("listings")}
    assert listing_uniques == {
        "uq_listings_provider_provider_security_id": ["provider", "provider_security_id"],
        "uq_listings_provider_nse_symbol": ["provider", "nse_symbol"],
        "uq_listings_provider_bse_code": ["provider", "bse_code"],
    }
    assert {c["name"] for c in inspector.get_check_constraints("listings")} == {
        "ck_listings_nse_symbol_format", "ck_listings_bse_code_format", "ck_listings_isin_format",
    }

    price_uniques = {u["name"]: u["column_names"] for u in inspector.get_unique_constraints("daily_prices")}
    assert price_uniques == {"uq_daily_prices_listing_id_exchange_trade_date": ["listing_id", "exchange", "trade_date"]}
    assert {c["name"] for c in inspector.get_check_constraints("daily_prices")} == {
        "ck_daily_prices_exchange_valid", "ck_daily_prices_close_price_positive", "ck_daily_prices_volume_non_negative",
    }
    foreign_keys = {fk["referred_table"]: fk["options"].get("ondelete") for fk in inspector.get_foreign_keys("daily_prices")}
    assert foreign_keys == {"listings": "CASCADE", "market_data_sync_runs": "SET NULL"}
    columns = {c["name"]: c for c in inspector.get_columns("daily_prices")}
    assert str(columns["close_price"]["type"]) == "NUMERIC(18, 4)"
    assert str(columns["trade_date"]["type"]) == "DATE"

    assert {c["name"] for c in inspector.get_check_constraints("market_data_sync_runs")} == {
        "ck_market_data_sync_runs_kind_valid",
        "ck_market_data_sync_runs_status_valid",
        "ck_market_data_sync_runs_counters_non_negative",
    }


def test_row_level_security_is_enabled_on_every_table(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'"
            )
        ).all()

    tables = {name: (enabled, forced) for name, enabled, forced in rows}
    assert set(tables) == {"portfolios", "holdings", "listings", "daily_prices", "market_data_sync_runs", "alembic_version"}
    # Enabled for hosted Data API roles; not forced, so the owning application role is unaffected.
    assert all(enabled and not forced for enabled, forced in tables.values()), tables


def test_migration_matches_models(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []
