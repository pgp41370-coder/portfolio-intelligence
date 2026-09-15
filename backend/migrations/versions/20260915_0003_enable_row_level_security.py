"""Enable row-level security on every application table.

Hosted PostgreSQL platforms such as Supabase expose tables in the public schema through a
REST Data API. With row-level security enabled and no policies, the Data API roles can
neither read nor write these tables. The application connects as the table owner, which
is not subject to row-level security unless it is forced, so its behaviour is unchanged.

No tables, columns or rows change.

Revision ID: 20260915_0003
Revises: 20260915_0002
Create Date: 2026-09-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_0003"
down_revision: str | None = "20260915_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("portfolios", "holdings", "listings", "market_data_sync_runs", "daily_prices", "alembic_version")


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
