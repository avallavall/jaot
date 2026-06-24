"""audit_logs reference_type + reference_id (Phase 7.1 Plan 02 / D-7.1-12).

Additive ALTER TABLE: adds two nullable columns + a partial index so
future audits can filter audit_logs by (reference_type, reference_id)
cheaply without a full table scan. Symmetric with the notification
migration (20260424_notif_reference_id) that ships in Plan 01.

Threat model T-07.1-06: reference_id is internal prefixed id (lic_*)
already present in target_id. The new columns are a parallel
denormalisation — no new data surface.
Threat model T-07.1-07: additive ADD COLUMN only. No DROP/RENAME.

Revision ID: 20260424b_audit_log_ref_id
Revises: 20260424_notif_reference_id
Create Date: 2026-04-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260424b_audit_log_ref_id"
down_revision = "20260424_notif_reference_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("reference_type", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("reference_id", sa.String(length=64), nullable=True),
    )
    # Partial index — only indexed when reference_type is set, keeping it
    # small for the vast majority of audit rows that don't reference a
    # specific entity.
    op.create_index(
        "idx_audit_logs_reference",
        "audit_logs",
        ["reference_type", "reference_id"],
        unique=False,
        postgresql_where=sa.text("reference_type IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_audit_logs_reference", table_name="audit_logs")
    op.drop_column("audit_logs", "reference_id")
    op.drop_column("audit_logs", "reference_type")
