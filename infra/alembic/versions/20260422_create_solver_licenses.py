"""create solver_licenses table

Phase 7 / HEX-02 / D-01. Additive-only migration (CLAUDE.md):
CREATE TABLE + CREATE INDEX only. No DROP / RENAME. Downgrade
drops the index then the table cleanly.

Schema matches ``app.models.solver_license.SolverLicense``:
- id (str, PK, prefixed ``lic_``)
- organization_id (FK organizations.id ON DELETE CASCADE, indexed)
- solver_name (str)
- encrypted_payload (JSONB — Fernet ciphertext wrapper)
- expires_at (nullable, indexed for the daily expiry sweep)
- last_validated_at
- fingerprint (sha256 first-8-hex, safe for UI display)
- created_at
- created_by_user_id (FK users.id ON DELETE SET NULL)

Constraints:
- Unique (organization_id, solver_name) — one license per solver per org.
- Index on expires_at — used by the 7-day expiry sweep (Plan 06).

Revision ID: 20260422_create_solver_licenses
Revises: 20260418_refund_unique
Create Date: 2026-04-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "20260422_create_solver_licenses"
down_revision = "20260418_refund_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "solver_licenses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("solver_name", sa.String(32), nullable=False),
        sa.Column("encrypted_payload", JSONB, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("last_validated_at", sa.DateTime, nullable=False),
        sa.Column("fingerprint", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "organization_id",
            "solver_name",
            name="ux_solver_licenses_org_solver",
        ),
    )
    op.create_index(
        "ix_solver_licenses_expires_at",
        "solver_licenses",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_solver_licenses_expires_at", table_name="solver_licenses")
    op.drop_table("solver_licenses")
