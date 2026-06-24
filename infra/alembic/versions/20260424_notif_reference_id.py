"""Notification reference_type + reference_id (E-12, Phase 7.1 / D-7.1-09).

Additive ALTER TABLE: adds two nullable columns + a partial index so
the beat-sweep dedup query in app/tasks/license_tasks.py can filter by
(reference_type, reference_id) instead of the per-org `link` column
(which silences BYOL solvers 2..N when solver 1 fires first in the
24h dedup window).

Revision ID: 20260424_notif_reference_id
Revises: 20260423_solver_license_tz_aware
Create Date: 2026-04-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260424_notif_reference_id"
down_revision = "20260423_solver_license_tz_aware"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("reference_type", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("reference_id", sa.String(length=64), nullable=True),
    )
    # Partial index — only rows with a reference_type are indexed. Keeps the
    # index small (pre-migration rows have NULL both columns) and speeds up
    # the dedup query WHERE reference_type = 'solver_license' AND reference_id IN (...).
    op.create_index(
        "idx_notifications_reference",
        "notifications",
        ["reference_type", "reference_id"],
        unique=False,
        postgresql_where=sa.text("reference_type IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_notifications_reference", table_name="notifications")
    op.drop_column("notifications", "reference_id")
    op.drop_column("notifications", "reference_type")
