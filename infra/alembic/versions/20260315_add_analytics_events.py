"""Add analytics_events table for feature usage tracking

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-03-15
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "i0j1k2l3m4n5"
down_revision = "h9i0j1k2l3m4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Composite indexes for efficient time-range queries
    op.create_index(
        "ix_ae_event_type_created", "analytics_events", ["event_type", "created_at"]
    )
    op.create_index(
        "ix_ae_user_created", "analytics_events", ["user_id", "created_at"]
    )
    op.create_index("ix_ae_user_id", "analytics_events", ["user_id"])
    op.create_index("ix_ae_created_at", "analytics_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("analytics_events")
