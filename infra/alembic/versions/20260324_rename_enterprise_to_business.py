"""Rename enterprise plan to business.

Revision ID: 20260324_rename_enterprise
Revises: 20260322_financial_hardening_schema
Create Date: 2026-03-24
"""

from alembic import op

revision = "20260324_rename_enterprise"
down_revision = "b4c5d6e7f8g9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename enterprise plan to business in organizations table
    op.execute("UPDATE organizations SET plan = 'business' WHERE plan = 'enterprise'")

    # Update platform_settings keys that reference enterprise tier
    op.execute(
        "UPDATE platform_settings SET key = REPLACE(key, 'plan_enterprise_', 'plan_business_') "
        "WHERE key LIKE 'plan_enterprise_%'"
    )


def downgrade() -> None:
    op.execute("UPDATE organizations SET plan = 'enterprise' WHERE plan = 'business'")
    op.execute(
        "UPDATE platform_settings SET key = REPLACE(key, 'plan_business_', 'plan_enterprise_') "
        "WHERE key LIKE 'plan_business_%'"
    )
