"""Create portfolios and holdings tables.

Revision ID: 20260915_0001
Revises:
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Constraint names are wrapped in op.f() so the naming convention on the models'
# metadata is not applied a second time.


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name=op.f("ck_portfolios_name_not_blank")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolios")),
    )

    op.create_table(
        "holdings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("exchange", sa.String(length=3), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("average_buy_price", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_holdings_quantity_positive")),
        sa.CheckConstraint("average_buy_price > 0", name=op.f("ck_holdings_average_buy_price_positive")),
        sa.CheckConstraint("exchange IN ('NSE', 'BSE')", name=op.f("ck_holdings_exchange_valid")),
        sa.CheckConstraint("symbol ~ '^[A-Z0-9][A-Z0-9&-]{0,19}$'", name=op.f("ck_holdings_symbol_format")),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_holdings_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holdings")),
        sa.UniqueConstraint(
            "portfolio_id", "symbol", "exchange", name=op.f("uq_holdings_portfolio_id_symbol_exchange")
        ),
    )


def downgrade() -> None:
    op.drop_table("holdings")
    op.drop_table("portfolios")
