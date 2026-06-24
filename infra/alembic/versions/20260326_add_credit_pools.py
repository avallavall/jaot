"""Add credits_subscription and credits_purchased columns.

Separates credit balance into three pools:
- credits_subscription: refreshed monthly (use-it-or-lose-it)
- credits_purchased: from top-ups, never expire
- credits_earned: from marketplace sales (already exists)

Revision ID: 20260326_credit_pools
Revises: 20260324_rename_enterprise
Create Date: 2026-03-26
"""

import sqlalchemy as sa
from alembic import op

revision = "20260326_credit_pools"
down_revision = "20260324_rename_enterprise"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use raw SQL with IF NOT EXISTS to be idempotent
    op.execute(
        "ALTER TABLE organizations "
        "ADD COLUMN IF NOT EXISTS credits_subscription INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE organizations "
        "ADD COLUMN IF NOT EXISTS credits_purchased INTEGER NOT NULL DEFAULT 0"
    )
    # Initialize: assume all current balance is subscription credits
    # (purchased and earned are tracked separately already)
    op.execute(
        "UPDATE organizations "
        "SET credits_subscription = GREATEST(0, credits_balance - credits_earned) "
        "WHERE credits_subscription = 0"
    )


def downgrade() -> None:
    op.drop_column("organizations", "credits_purchased")
    op.drop_column("organizations", "credits_subscription")
