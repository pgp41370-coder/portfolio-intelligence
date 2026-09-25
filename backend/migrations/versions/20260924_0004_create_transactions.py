"""Create the transaction ledger.

Additive only: portfolios, holdings and the market-data tables are untouched, and a
portfolio with no transactions behaves exactly as before. Row-level security is enabled to
match the policy migration 20260915_0003 applies to every other table.

Revision ID: 20260924_0004
Revises: 20260915_0003
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0004"
down_revision: str | None = "20260915_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("exchange", sa.String(length=3), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("price", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("fees", sa.Numeric(precision=14, scale=4), server_default=sa.text("0"), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_transactions_quantity_positive")),
        sa.CheckConstraint("price > 0", name=op.f("ck_transactions_price_positive")),
        sa.CheckConstraint("fees >= 0", name=op.f("ck_transactions_fees_not_negative")),
        sa.CheckConstraint("kind IN ('BUY', 'SELL')", name=op.f("ck_transactions_kind_valid")),
        sa.CheckConstraint("exchange IN ('NSE', 'BSE')", name=op.f("ck_transactions_exchange_valid")),
        sa.CheckConstraint("symbol ~ '^[A-Z0-9][A-Z0-9&-]{0,19}$'", name=op.f("ck_transactions_symbol_format")),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_transactions_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index("ix_transactions_portfolio_id_trade_date", "transactions", ["portfolio_id", "trade_date"])
    op.create_index(
        "ix_transactions_portfolio_id_symbol_exchange",
        "transactions",
        ["portfolio_id", "symbol", "exchange", "trade_date"],
    )
    op.execute("ALTER TABLE transactions ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_transactions_portfolio_id_symbol_exchange", table_name="transactions")
    op.drop_index("ix_transactions_portfolio_id_trade_date", table_name="transactions")
    op.drop_table("transactions")
