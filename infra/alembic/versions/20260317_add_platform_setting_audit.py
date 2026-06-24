"""Add platform_setting_audit table for admin settings audit trail

Revision ID: j1k2l3m4n5o6
Revises: i0j1k2l3m4n5
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "j1k2l3m4n5o6"
down_revision = "i0j1k2l3m4n5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_setting_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("setting_key", sa.String(length=100), nullable=False),
        sa.Column("old_value", sa.String(length=500), nullable=True),
        sa.Column("new_value", sa.String(length=500), nullable=True),
        sa.Column("changed_by", sa.String(length=255), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_psa_setting_key", "platform_setting_audit", ["setting_key"])
    op.create_index("ix_psa_changed_at", "platform_setting_audit", ["changed_at"])


def downgrade() -> None:
    op.drop_index("ix_psa_changed_at", table_name="platform_setting_audit")
    op.drop_index("ix_psa_setting_key", table_name="platform_setting_audit")
    op.drop_table("platform_setting_audit")
