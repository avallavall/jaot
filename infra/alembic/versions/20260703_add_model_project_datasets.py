"""Add ModelProjectDataset — named data bundles ("scenarios") per project (§8)

One CREATE TABLE: ``model_project_datasets`` holds the set members + param values
(``data_json``, the JModelData JSON shape) that fill a declaration-only JModel
source at compile time. One model, many named datasets — the model↔data seam.

Additive-only per root CLAUDE.md "Migrations" rule: no DROP/RENAME, no backfill.

Revision ID: 20260703_model_project_datasets
Revises: 20260629_relax_max_vars
Create Date: 2026-07-03
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260703_model_project_datasets"
down_revision = "20260629_relax_max_vars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_project_datasets",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "model_project_id",
            sa.String(length=64),
            sa.ForeignKey("model_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.String(length=64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_mpd_project", "model_project_datasets", ["model_project_id"])
    op.create_index(
        "ix_mpd_project_name",
        "model_project_datasets",
        ["model_project_id", "name"],
        unique=True,
    )
    op.create_index("ix_mpd_org", "model_project_datasets", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_mpd_org", table_name="model_project_datasets")
    op.drop_index("ix_mpd_project_name", table_name="model_project_datasets")
    op.drop_index("ix_mpd_project", table_name="model_project_datasets")
    op.drop_table("model_project_datasets")
