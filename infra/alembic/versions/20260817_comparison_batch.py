"""Group comparisons that were launched together as one matrix.

A matrix crosses several datasets with several solvers. Each dataset is still one
comparison, because a comparison is what carries the terms every solver received;
what was missing was the thread that ties the rows of one launch together.

``batch_id`` is that thread and ``batch_position`` is the order the user picked
the datasets in, which is also the order they run in. Both are nullable, so every
comparison created before this migration keeps working as a batch of one.

Revision ID: 20260817_comparison_batch
Revises: 20260814_comparison_shape
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260817_comparison_batch"
down_revision = "20260814_comparison_shape"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("solver_comparisons", sa.Column("batch_id", sa.String(length=64), nullable=True))
    op.add_column("solver_comparisons", sa.Column("batch_position", sa.Integer(), nullable=True))
    op.create_index(
        "ix_solver_comparisons_batch_id", "solver_comparisons", ["batch_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_solver_comparisons_batch_id", table_name="solver_comparisons")
    op.drop_column("solver_comparisons", "batch_position")
    op.drop_column("solver_comparisons", "batch_id")
