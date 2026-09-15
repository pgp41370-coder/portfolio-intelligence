"""Create market-data tables: listings, daily_prices and market_data_sync_runs.

Additive only: portfolios and holdings are not changed.

Revision ID: 20260915_0002
Revises: 20260915_0001
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260915_0002"
down_revision: str | None = "20260915_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_security_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("nse_symbol", sa.String(length=20), nullable=True),
        sa.Column("bse_code", sa.String(length=6), nullable=True),
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prices_last_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prices_last_request_status", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("nse_symbol ~ '^[A-Z0-9][A-Z0-9&-]{0,19}$'", name=op.f("ck_listings_nse_symbol_format")),
        sa.CheckConstraint("bse_code ~ '^[0-9]{6}$'", name=op.f("ck_listings_bse_code_format")),
        sa.CheckConstraint("isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'", name=op.f("ck_listings_isin_format")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listings")),
        sa.UniqueConstraint("provider", "provider_security_id", name=op.f("uq_listings_provider_provider_security_id")),
        sa.UniqueConstraint("provider", "nse_symbol", name=op.f("uq_listings_provider_nse_symbol")),
        sa.UniqueConstraint("provider", "bse_code", name=op.f("uq_listings_provider_bse_code")),
    )

    op.create_table(
        "market_data_sync_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requests_made", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_attempted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_inserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.CheckConstraint("kind IN ('security_master', 'daily_prices')", name=op.f("ck_market_data_sync_runs_kind_valid")),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed', 'rate_limited', 'budget_exhausted')",
            name=op.f("ck_market_data_sync_runs_status_valid"),
        ),
        sa.CheckConstraint(
            "requests_made >= 0 AND records_attempted >= 0 AND records_inserted >= 0 "
            "AND records_updated >= 0 AND failures >= 0",
            name=op.f("ck_market_data_sync_runs_counters_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_data_sync_runs")),
    )
    op.create_index(
        op.f("ix_market_data_sync_runs_provider_kind_started_at"),
        "market_data_sync_runs",
        ["provider", "kind", "started_at"],
    )

    op.create_table(
        "daily_prices",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("exchange", sa.String(length=3), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("close_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("exchange IN ('NSE', 'BSE')", name=op.f("ck_daily_prices_exchange_valid")),
        sa.CheckConstraint("close_price > 0", name=op.f("ck_daily_prices_close_price_positive")),
        sa.CheckConstraint("volume IS NULL OR volume >= 0", name=op.f("ck_daily_prices_volume_non_negative")),
        sa.ForeignKeyConstraint(
            ["listing_id"], ["listings.id"], name=op.f("fk_daily_prices_listing_id_listings"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["market_data_sync_runs.id"],
            name=op.f("fk_daily_prices_sync_run_id_market_data_sync_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_prices")),
        sa.UniqueConstraint(
            "listing_id", "exchange", "trade_date", name=op.f("uq_daily_prices_listing_id_exchange_trade_date")
        ),
    )


def downgrade() -> None:
    op.drop_table("daily_prices")
    op.drop_index(op.f("ix_market_data_sync_runs_provider_kind_started_at"), table_name="market_data_sync_runs")
    op.drop_table("market_data_sync_runs")
    op.drop_table("listings")
