"""Let a trigger fire a studio model, not only a builder document.

A trigger could only ever point at a ``model_builder_documents`` row plus one of
its version snapshots, and both columns were NOT NULL. The studio never creates a
builder document — and since the P1.5 fusion the studio is where models are built
— so nothing anyone builds today could be automated at all.

Additive, as the migration rules require: two new nullable columns for the
project pair, and the two existing columns relaxed to nullable so a trigger can
carry one pair or the other. Nothing is dropped or renamed, and every existing
trigger keeps its document pair exactly as it was, so a rollback to the previous
image finds every row it wrote still valid.

Revision ID: 20260801_triggers_studio
Revises: 20260801_contract_release
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260801_triggers_studio"
down_revision = "20260801_contract_release"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "solve_triggers",
        sa.Column("model_project_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "solve_triggers",
        sa.Column("model_project_version_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_solve_triggers_model_project_id",
        "solve_triggers",
        ["model_project_id"],
    )
    op.create_foreign_key(
        "fk_solve_triggers_model_project_id",
        "solve_triggers",
        "model_projects",
        ["model_project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # RESTRICT, like the builder pair: a pinned version must not vanish under a
    # trigger that still points at it.
    op.create_foreign_key(
        "fk_solve_triggers_model_project_version_id",
        "solve_triggers",
        "model_project_versions",
        ["model_project_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # The builder pair becomes optional; existing rows are untouched.
    op.alter_column(
        "solve_triggers", "document_id", existing_type=sa.String(length=64), nullable=True
    )
    op.alter_column(
        "solve_triggers", "version_id", existing_type=sa.String(length=64), nullable=True
    )


def downgrade() -> None:
    # Restoring NOT NULL would fail on any trigger created against a studio model,
    # so the down path drops those rows' claim rather than the rows themselves:
    # the columns go, and with them the project triggers' target. Deliberate and
    # one-way — the release notes say a rollback restores the image, not the data.
    op.drop_constraint(
        "fk_solve_triggers_model_project_version_id", "solve_triggers", type_="foreignkey"
    )
    op.drop_constraint("fk_solve_triggers_model_project_id", "solve_triggers", type_="foreignkey")
    op.drop_index("ix_solve_triggers_model_project_id", table_name="solve_triggers")
    op.drop_column("solve_triggers", "model_project_version_id")
    op.drop_column("solve_triggers", "model_project_id")
    op.alter_column(
        "solve_triggers", "version_id", existing_type=sa.String(length=64), nullable=False
    )
    op.alter_column(
        "solve_triggers", "document_id", existing_type=sa.String(length=64), nullable=False
    )
