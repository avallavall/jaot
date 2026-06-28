"""Add execution provenance: richer origin + source_kind/source_id

Makes every model execution navigable back to the object that produced it
(builder document, LLM conversation, template, organization model, trigger,
imported file) and distinguishes the creation channel via a richer ``origin``.

Additive-only per root CLAUDE.md "Migrations" rule:
  - ``origin`` widened VARCHAR(16) -> VARCHAR(32) (a grow is non-destructive;
    existing values keep their "manual"/"triggered" content).
  - two nullable ADD COLUMNs (``source_kind``, ``source_id``) with indexes.
No DROP/RENAME, no backfill. Pre-existing rows keep NULL source (= origin
already encodes what we know; navigation simply unavailable for old rows).

Revision ID: 20260628_exec_provenance
Revises: 20260626_org_anthropic_key
Create Date: 2026-06-28
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260628_exec_provenance"
down_revision = "20260626_org_anthropic_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "model_executions",
        "origin",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
        existing_server_default="manual",
    )
    op.add_column(
        "model_executions",
        sa.Column("source_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "model_executions",
        sa.Column("source_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_model_executions_source_kind",
        "model_executions",
        ["source_kind"],
    )
    op.create_index(
        "ix_model_executions_source_id",
        "model_executions",
        ["source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_executions_source_id", table_name="model_executions")
    op.drop_index("ix_model_executions_source_kind", table_name="model_executions")
    op.drop_column("model_executions", "source_id")
    op.drop_column("model_executions", "source_kind")
    op.alter_column(
        "model_executions",
        "origin",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default="manual",
    )
