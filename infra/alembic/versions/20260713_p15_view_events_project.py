"""P1.5 G1 — key marketplace view events on the unified Model (model_project_id).

The fusion serves the marketplace from ``model_project_listings``; fresh installs
have no ``model_catalog`` row, so a view/impression event can no longer require a
``catalog_model_id`` (its FK would break). Make ``catalog_model_id`` NULLABLE
(additive) and add a ``(model_project_id, event_type, created_at)`` index for the
now-project-keyed aggregation queries. The legacy column + its index stay inert
until the contract release drops them.

Revision ID: 20260713_p15_view_events
Revises: 20260712_p15_backfill
Create Date: 2026-07-13
"""

from alembic import op

revision = "20260713_p15_view_events"
down_revision = "20260712_p15_backfill"
branch_labels = None
depends_on = None

_TABLE = "model_view_events"
_INDEX = "ix_mve_project_type_created"


def upgrade() -> None:
    op.alter_column(_TABLE, "catalog_model_id", nullable=True)
    op.create_index(
        _INDEX, _TABLE, ["model_project_id", "event_type", "created_at"], if_not_exists=True
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE, if_exists=True)
    # Re-tighten only if no NULL rows exist (best-effort; the column pre-dates the nulls).
    op.execute(
        f'ALTER TABLE "{_TABLE}" ALTER COLUMN catalog_model_id SET NOT NULL'  # noqa: S608
    )
