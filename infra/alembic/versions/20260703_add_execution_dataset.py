"""Add dataset provenance to model_executions (§8 Scenarios / S1)

Two nullable ADD COLUMNs on ``model_executions``: ``dataset_id`` (indexed — the
S3 scenario-comparison table groups the latest execution per dataset) and
``dataset_name`` (a SNAPSHOT so history survives dataset deletion — datasets are
hard-deletable working data). Not FKs on purpose, same rationale as
source_kind/source_id.

Additive-only per root CLAUDE.md "Migrations" rule: no DROP/RENAME, no backfill.

Revision ID: 20260703_execution_dataset
Revises: 20260703_model_project_datasets
Create Date: 2026-07-03
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260703_execution_dataset"
down_revision = "20260703_model_project_datasets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_executions",
        sa.Column("dataset_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "model_executions",
        sa.Column("dataset_name", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_model_executions_dataset_id", "model_executions", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_model_executions_dataset_id", table_name="model_executions")
    op.drop_column("model_executions", "dataset_name")
    op.drop_column("model_executions", "dataset_id")
