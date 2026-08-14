"""Record what the compared problem is, next to the comparison.

The table showed a verdict per solver and nothing about the model they were
solving. How many variables, how many constraints and which class it belongs to
are the context that makes the rest readable — twelve seconds means one thing on
an LP and another on a mixed-integer model with twenty thousand rows.

Stored rather than derived on read. The class needs every constraint parsed, and
the page polls the comparison every two seconds while it runs; deriving it there
would re-parse the whole model on each tick. All three are written once, when the
comparison is created.

Nullable, so comparisons created before this migration keep working with the
fields simply absent.

Revision ID: 20260814_comparison_shape
Revises: 20260814_solver_comparisons
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260814_comparison_shape"
down_revision = "20260814_solver_comparisons"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "solver_comparisons", sa.Column("problem_class", sa.String(length=16), nullable=True)
    )
    op.add_column("solver_comparisons", sa.Column("variable_count", sa.Integer(), nullable=True))
    op.add_column("solver_comparisons", sa.Column("constraint_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("solver_comparisons", "constraint_count")
    op.drop_column("solver_comparisons", "variable_count")
    op.drop_column("solver_comparisons", "problem_class")
