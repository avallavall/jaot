"""Solver comparison: one problem, several solvers, identical settings.

Creates ``solver_comparisons`` and links ``model_executions`` to it with a new
nullable ``comparison_id``. Every existing execution keeps NULL there, so nothing
already in the table changes meaning.

The FK cascades on delete. Deleting a comparison deletes its child executions,
which is what makes an uploaded throwaway problem actually go away: the problem
snapshot lives in the parent row and in each child's ``input_data``, and both are
removed by the same delete.

Fully reversible. ``downgrade`` drops the column first and then the table, and
restores the schema to exactly what it was.

Revision ID: 20260814_solver_comparisons
Revises: 20260803_delete_org_cascade
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260814_solver_comparisons"
down_revision = "20260803_delete_org_cascade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "solver_comparisons",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
        # What is compared
        sa.Column("problem_data", sa.JSON(), nullable=False),
        sa.Column("problem_name", sa.String(length=255), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("uploaded_filename", sa.String(length=255), nullable=True),
        sa.Column("model_project_id", sa.String(length=64), nullable=True),
        sa.Column("model_project_version_id", sa.String(length=64), nullable=True),
        sa.Column("dataset_id", sa.String(length=64), nullable=True),
        sa.Column("dataset_name", sa.String(length=255), nullable=True),
        # The settings every solver received
        sa.Column("time_limit_seconds", sa.Float(), nullable=False),
        sa.Column("gap_tolerance", sa.Float(), nullable=False),
        sa.Column("threads", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("solver_names", sa.JSON(), nullable=False),
        # Run state
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("machine_note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_solver_comparisons_organization_id", "solver_comparisons", ["organization_id"]
    )
    op.create_index("ix_solver_comparisons_status", "solver_comparisons", ["status"])
    op.create_index("ix_solver_comparisons_created_at", "solver_comparisons", ["created_at"])
    op.create_index(
        "ix_solver_comparisons_celery_task_id", "solver_comparisons", ["celery_task_id"]
    )
    op.create_index(
        "ix_solver_comparisons_model_project_id", "solver_comparisons", ["model_project_id"]
    )
    op.create_index(
        "ix_solver_comparisons_org_created", "solver_comparisons", ["organization_id", "created_at"]
    )

    op.add_column(
        "model_executions",
        sa.Column("comparison_id", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_model_executions_comparison_id", "model_executions", ["comparison_id"])
    op.create_foreign_key(
        "fk_model_executions_comparison_id",
        "model_executions",
        "solver_comparisons",
        ["comparison_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_model_executions_comparison_id", "model_executions", type_="foreignkey")
    op.drop_index("ix_model_executions_comparison_id", table_name="model_executions")
    op.drop_column("model_executions", "comparison_id")

    op.drop_index("ix_solver_comparisons_org_created", table_name="solver_comparisons")
    op.drop_index("ix_solver_comparisons_model_project_id", table_name="solver_comparisons")
    op.drop_index("ix_solver_comparisons_celery_task_id", table_name="solver_comparisons")
    op.drop_index("ix_solver_comparisons_created_at", table_name="solver_comparisons")
    op.drop_index("ix_solver_comparisons_status", table_name="solver_comparisons")
    op.drop_index("ix_solver_comparisons_organization_id", table_name="solver_comparisons")
    op.drop_table("solver_comparisons")
