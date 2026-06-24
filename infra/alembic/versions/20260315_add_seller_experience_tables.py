"""Add seller experience tables: model_view_events, featured_placements,
verification_requests, notification_preferences

Revision ID: h9i0j1k2l3m4
Revises: g8h9i0j1k2l3
Create Date: 2026-03-15
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "h9i0j1k2l3m4"
down_revision = "g8h9i0j1k2l3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # model_view_events -- impression and view tracking for analytics
    op.create_table(
        "model_view_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("catalog_model_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("viewer_organization_id", sa.String(length=64), nullable=True),
        sa.Column("viewer_country", sa.String(length=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["catalog_model_id"],
            ["model_catalog.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mve_catalog_model_id", "model_view_events", ["catalog_model_id"])
    op.create_index("ix_mve_created_at", "model_view_events", ["created_at"])
    op.create_index(
        "ix_mve_model_type_created",
        "model_view_events",
        ["catalog_model_id", "event_type", "created_at"],
    )

    # featured_placements -- purchased promotions
    op.create_table(
        "featured_placements",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("catalog_model_id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("placement_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("credits_paid", sa.Integer(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["catalog_model_id"],
            ["model_catalog.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fp_catalog_model_id", "featured_placements", ["catalog_model_id"])
    op.create_index("ix_fp_organization_id", "featured_placements", ["organization_id"])
    op.create_index("ix_fp_expires_at", "featured_placements", ["expires_at"])

    # verification_requests -- seller badge verification workflow
    op.create_table(
        "verification_requests",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vr_organization_id", "verification_requests", ["organization_id"])
    op.create_index("ix_vr_status", "verification_requests", ["status"])

    # notification_preferences -- per-user notification toggles
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "event_type", "channel", name="uq_notif_pref_user_event_channel"
        ),
    )
    op.create_index("ix_np_user_id", "notification_preferences", ["user_id"])


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_table("verification_requests")
    op.drop_table("featured_placements")
    op.drop_table("model_view_events")
