"""Let a trigger choose the solver it runs on.

A trigger ran on whatever solver its pinned version named. The only way to run
it on another was an override field with a default, and nothing applied that
default. The trigger page now has an edit form with a solver choice, stored
here. NULL keeps the pinned version's own choice, which is what every existing
trigger does today.

Additive and reversible: the downgrade drops the column.

Revision ID: 20260925_trigger_solver_name
Revises: 20260925_one_user_name
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_trigger_solver_name"
down_revision = "20260925_one_user_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("solve_triggers", sa.Column("solver_name", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("solve_triggers", "solver_name")
