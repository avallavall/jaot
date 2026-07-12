"""Make orphaned money columns nullable (ADR-008).

The credit system is removed: these columns are no longer ORM-mapped, so
inserts omit them — but they were created NOT NULL with Python-side (not
server-side) defaults, which broke every insert into their tables. Dropping
NOT NULL is an additive widening; the columns themselves stay until a later
release drops them. Dead tables (credit_transactions, withdrawals, invoices,
featured_placements, exchange_rates, usage_records, workspace_credit_pools)
receive no inserts anymore and are left untouched.

Revision ID: 20260711_money_nullable
Revises: 20260710_timestamptz
Create Date: 2026-07-11
"""

from alembic import op
from sqlalchemy import text

revision = "20260711_money_nullable"
down_revision = "20260710_timestamptz"
branch_labels = None
depends_on = None

_LIVE_MONEY_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column, downgrade backfill literal)
    ("model_catalog", "credits_per_execution", "1"),
    ("model_catalog", "price_eur", "0.0"),
    ("model_executions", "credits_base", "0"),
    ("model_executions", "credits_compute", "0"),
    ("model_executions", "credits_consumed", "0"),
    ("organization_models", "total_credits_used", "0"),
    ("organizations", "credits_balance", "0"),
    ("organizations", "credits_earned", "0"),
    ("organizations", "credits_used_month", "0"),
    ("organizations", "currency", "'EUR'"),
    ("organizations", "monthly_quota", "0"),
    ("trigger_runs", "credits_consumed", "0"),
]


def upgrade() -> None:
    for table, column, _ in _LIVE_MONEY_COLUMNS:
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP NOT NULL')


def downgrade() -> None:
    conn = op.get_bind()
    for table, column, fill in _LIVE_MONEY_COLUMNS:
        conn.execute(text(f'UPDATE "{table}" SET "{column}" = {fill} WHERE "{column}" IS NULL'))
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET NOT NULL')
