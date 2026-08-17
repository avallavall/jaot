"""Let a comparison exist before its problem has been compiled.

A matrix compiles one problem per dataset. Doing that inside the launch request
put the whole cost of the model in front of the user: measured at 28 seconds and
57 MB for three datasets of 22,500 variables, and past a proxy's ceiling for
twelve. The compile and the snapshot now happen on the worker, one row at a time,
so the launch returns as soon as the rows exist.

That means a comparison row is created before it has a problem, and
``problem_data`` has to be allowed to be empty until its worker fills it in. A
single comparison still arrives with its snapshot already in hand and never
passes through the empty state.

Revision ID: 20260817_lazy_snapshot
Revises: 20260817_comparison_batch
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260817_lazy_snapshot"
down_revision = "20260817_comparison_batch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("solver_comparisons", "problem_data", existing_type=sa.JSON(), nullable=True)


def downgrade() -> None:
    # Rows still waiting for their worker have no problem to write back, and a
    # comparison without one cannot be solved. Emptying them is what makes the
    # column NOT NULL again without inventing a problem nobody asked for.
    op.execute(
        "DELETE FROM model_executions WHERE comparison_id IN "
        "(SELECT id FROM solver_comparisons WHERE problem_data IS NULL)"
    )
    op.execute("DELETE FROM solver_comparisons WHERE problem_data IS NULL")
    op.alter_column("solver_comparisons", "problem_data", existing_type=sa.JSON(), nullable=False)
