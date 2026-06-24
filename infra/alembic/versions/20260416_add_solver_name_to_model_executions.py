"""Add solver_name column to model_executions.

Phase 5 / HIGH-07. Additive-only migration — no DROP, no RENAME, no backfill.
Existing rows will have NULL solver_name, which the frontend renders as "SCIP"
(see UI-SPEC §Execution Detail — Solver Field).

Revision ID: 20260416_solver_name
Revises: 20260327_seed_settings
Create Date: 2026-04-16
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260416_solver_name"
down_revision = "20260327_seed_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_executions",
        sa.Column("solver_name", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_model_exec_solver",
        "model_executions",
        ["solver_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_exec_solver", table_name="model_executions")
    op.drop_column("model_executions", "solver_name")
