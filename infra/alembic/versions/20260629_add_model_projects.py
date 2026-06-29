"""Add ModelProject + ModelProjectVersion (first-class model entity, P1a)

Creates the ``model_projects`` (mutable HEAD draft) and ``model_project_versions``
(immutable commit-grade snapshots) tables, and links existing tables to them.

Additive-only per root CLAUDE.md "Migrations" rule:
  - two CREATE TABLE.
  - nullable ADD COLUMNs on ``model_executions`` (model_project_id /
    model_project_version_id), ``llm_conversations`` (model_project_id) and
    ``organization_models`` (source_model_project_id), with indexes.
No DROP/RENAME, no backfill. The ``model_project`` source_kind value is a code-only
frozenset addition (the source_kind column is already VARCHAR(32)).

Revision ID: 20260629_model_projects
Revises: 20260628_exec_provenance
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260629_model_projects"
down_revision = "20260628_exec_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_projects",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            sa.String(length=64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.String(length=64),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("source_type", sa.String(length=32), nullable=True),
        sa.Column("source_ref", sa.String(length=128), nullable=True),
        sa.Column("current_version_id", sa.String(length=64), nullable=True),
        sa.Column("committed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("draft_model_json", sa.JSON(), nullable=True),
        sa.Column("draft_canvas_json", sa.JSON(), nullable=True),
        sa.Column("draft_dsl_source", sa.Text(), nullable=True),
        sa.Column("draft_content_hash", sa.String(length=64), nullable=True),
        sa.Column("draft_updated_at", sa.DateTime(), nullable=True),
        sa.Column("draft_lock_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_model_projects_organization_id", "model_projects", ["organization_id"]
    )
    op.create_index("ix_model_projects_org_status", "model_projects", ["organization_id", "status"])
    op.create_index(
        "ix_model_projects_org_updated", "model_projects", ["organization_id", "updated_at"]
    )

    op.create_table(
        "model_project_versions",
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
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(length=64), nullable=True),
        sa.Column("model_json", sa.JSON(), nullable=False),
        sa.Column("canvas_json", sa.JSON(), nullable=True),
        sa.Column("dsl_source", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("commit_summary", sa.String(length=500), nullable=False),
        sa.Column("commit_body", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stats_json", sa.JSON(), nullable=True),
        sa.Column("problem_class", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_mpv_project", "model_project_versions", ["model_project_id"])
    op.create_index(
        "ix_mpv_project_sequence",
        "model_project_versions",
        ["model_project_id", "sequence"],
        unique=True,
    )
    op.create_index(
        "ix_mpv_org_created", "model_project_versions", ["organization_id", "created_at"]
    )
    op.create_index("ix_mpv_content_hash", "model_project_versions", ["content_hash"])

    # Per-project execution history (nullable, indexed).
    op.add_column(
        "model_executions",
        sa.Column("model_project_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "model_executions",
        sa.Column("model_project_version_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_model_executions_model_project_id", "model_executions", ["model_project_id"]
    )
    op.create_index(
        "ix_model_executions_model_project_version_id",
        "model_executions",
        ["model_project_version_id"],
    )

    # The AI tab's conversation belongs to a project (P2 scope; column added now).
    op.add_column(
        "llm_conversations",
        sa.Column("model_project_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_llm_conversations_model_project_id", "llm_conversations", ["model_project_id"]
    )

    # A published marketplace listing can point back at its authoring project (P1.5).
    op.add_column(
        "organization_models",
        sa.Column("source_model_project_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organization_models", "source_model_project_id")
    op.drop_index("ix_llm_conversations_model_project_id", table_name="llm_conversations")
    op.drop_column("llm_conversations", "model_project_id")
    op.drop_index(
        "ix_model_executions_model_project_version_id", table_name="model_executions"
    )
    op.drop_index("ix_model_executions_model_project_id", table_name="model_executions")
    op.drop_column("model_executions", "model_project_version_id")
    op.drop_column("model_executions", "model_project_id")

    op.drop_index("ix_mpv_content_hash", table_name="model_project_versions")
    op.drop_index("ix_mpv_org_created", table_name="model_project_versions")
    op.drop_index("ix_mpv_project_sequence", table_name="model_project_versions")
    op.drop_index("ix_mpv_project", table_name="model_project_versions")
    op.drop_table("model_project_versions")

    op.drop_index("ix_model_projects_org_updated", table_name="model_projects")
    op.drop_index("ix_model_projects_org_status", table_name="model_projects")
    op.drop_index("ix_model_projects_organization_id", table_name="model_projects")
    op.drop_table("model_projects")
