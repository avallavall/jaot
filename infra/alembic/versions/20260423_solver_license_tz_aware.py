"""solver_licenses datetime columns -> timezone-aware

Phase 7 / simplify-2 / R-22. Additive ALTER COLUMN (per CLAUDE.md):
converts ``solver_licenses.expires_at``, ``last_validated_at``, and
``created_at`` from ``timestamp without time zone`` to
``timestamp with time zone``. In-place via ``USING ... AT TIME ZONE 'UTC'``
— Postgres rewrites the column metadata, no data loss, existing naive
values are reinterpreted as UTC (which matches production since every
write goes through ``utcnow()``).

Why: the naive-column + tz-aware-helper mismatch forced every read site
(``license_service`` / ``license_tasks``) to sprinkle
``now.replace(tzinfo=None)`` guards before comparing against column
values. With tz-aware columns those helpers collapse to direct
``row.expires_at < utcnow()`` comparisons.

Revision ID: 20260423_solver_license_tz_aware
Revises: 20260422_create_solver_licenses
Create Date: 2026-04-23
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260423_solver_license_tz_aware"
down_revision = "20260422_create_solver_licenses"
branch_labels = None
depends_on = None


_COLS = ("expires_at", "last_validated_at", "created_at")


def upgrade() -> None:
    for col in _COLS:
        # USING ... AT TIME ZONE 'UTC' treats existing naive values as UTC
        # (matches production — every write uses utcnow()). Postgres
        # performs this as a pure metadata rewrite.
        op.execute(
            f"ALTER TABLE solver_licenses "
            f"ALTER COLUMN {col} TYPE timestamp with time zone "
            f"USING {col} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    for col in _COLS:
        # Reverse: drop the tz info, storing the UTC instant as naive.
        op.execute(
            f"ALTER TABLE solver_licenses "
            f"ALTER COLUMN {col} TYPE timestamp without time zone "
            f"USING {col} AT TIME ZONE 'UTC'"
        )
