"""add workspace collaboration tables

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-02-21 10:00:00.000000+00:00

Tables created:
- workspaces
- workspace_members (with unique constraint on workspace_id + user_id)
- workspace_invites
- audit_logs (with composite index on organization_id + created_at)
- workspace_credit_pools

Columns added to existing tables:
- organizations.owner_user_id (String(64), nullable)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. workspaces
    # ------------------------------------------------------------------ #
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_workspaces_organization_id"),
            ["organization_id"],
            unique=False,
        )

    # ------------------------------------------------------------------ #
    # 2. workspace_members
    # ------------------------------------------------------------------ #
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("invited_by", sa.String(length=64), nullable=True),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )
    with op.batch_alter_table("workspace_members", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_workspace_members_workspace_id"),
            ["workspace_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_workspace_members_user_id"),
            ["user_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_workspace_members_organization_id"),
            ["organization_id"],
            unique=False,
        )

    # ------------------------------------------------------------------ #
    # 3. workspace_invites
    # ------------------------------------------------------------------ #
    op.create_table(
        "workspace_invites",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("invitee_email", sa.String(length=255), nullable=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_by", sa.String(length=64), nullable=True),
        sa.Column("is_revoked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    with op.batch_alter_table("workspace_invites", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_workspace_invites_workspace_id"),
            ["workspace_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_workspace_invites_token_hash"),
            ["token_hash"],
            unique=True,
        )

    # ------------------------------------------------------------------ #
    # 4. audit_logs
    # ------------------------------------------------------------------ #
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("actor_name", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("target_name", sa.String(length=255), nullable=True),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_audit_logs_organization_id"),
            ["organization_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_audit_logs_workspace_id"),
            ["workspace_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_audit_logs_actor_id"),
            ["actor_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_audit_logs_action"),
            ["action"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_audit_logs_created_at"),
            ["created_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_audit_logs_org_created_at",
            ["organization_id", "created_at"],
            unique=False,
        )

    # ------------------------------------------------------------------ #
    # 5. workspace_credit_pools
    # ------------------------------------------------------------------ #
    op.create_table(
        "workspace_credit_pools",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("allocated_credits", sa.Integer(), nullable=False),
        sa.Column("used_credits", sa.Integer(), nullable=False),
        sa.Column("last_alert_threshold", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id"),
    )
    with op.batch_alter_table("workspace_credit_pools", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_workspace_credit_pools_workspace_id"),
            ["workspace_id"],
            unique=True,
        )
        batch_op.create_index(
            batch_op.f("ix_workspace_credit_pools_organization_id"),
            ["organization_id"],
            unique=False,
        )

    # ------------------------------------------------------------------ #
    # 6. organizations — add owner_user_id column
    # ------------------------------------------------------------------ #
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("owner_user_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    # ------------------------------------------------------------------ #
    # Reverse order: dependent tables first
    # ------------------------------------------------------------------ #

    # Remove owner_user_id from organizations
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.drop_column("owner_user_id")

    # workspace_credit_pools
    with op.batch_alter_table("workspace_credit_pools", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workspace_credit_pools_organization_id"))
        batch_op.drop_index(batch_op.f("ix_workspace_credit_pools_workspace_id"))
    op.drop_table("workspace_credit_pools")

    # audit_logs
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.drop_index("ix_audit_logs_org_created_at")
        batch_op.drop_index(batch_op.f("ix_audit_logs_created_at"))
        batch_op.drop_index(batch_op.f("ix_audit_logs_action"))
        batch_op.drop_index(batch_op.f("ix_audit_logs_actor_id"))
        batch_op.drop_index(batch_op.f("ix_audit_logs_workspace_id"))
        batch_op.drop_index(batch_op.f("ix_audit_logs_organization_id"))
    op.drop_table("audit_logs")

    # workspace_invites
    with op.batch_alter_table("workspace_invites", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workspace_invites_token_hash"))
        batch_op.drop_index(batch_op.f("ix_workspace_invites_workspace_id"))
    op.drop_table("workspace_invites")

    # workspace_members
    with op.batch_alter_table("workspace_members", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workspace_members_organization_id"))
        batch_op.drop_index(batch_op.f("ix_workspace_members_user_id"))
        batch_op.drop_index(batch_op.f("ix_workspace_members_workspace_id"))
    op.drop_table("workspace_members")

    # workspaces (last — others depend on it)
    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workspaces_organization_id"))
    op.drop_table("workspaces")
