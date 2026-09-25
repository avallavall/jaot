"""Remember when a member was removed from a workspace, and name the join event.

A link invite is used by many people for 7 days. Removing a member deleted
their membership row and nothing else, so the removed person opened the same
link again and was back in, with the link's role. ``workspace_removals`` keeps
one row per (workspace, user) with the time of the last removal. Accepting an
invite created before that time is refused.

The same change gives joining its own audit action. Accepting an invite was
logged as ``member_invite``, so the log said "Member Invited" for the person who
had just joined. The rows written that way carry ``"action": "accepted"`` in
their metadata; they are relabelled ``member_join``.

Reversible: the down leg drops the table and labels every ``member_join`` row
``member_invite`` again, the only label the older code knows for a join.

Revision ID: 20260925_workspace_removals
Revises: 20260924_drop_billing_tables
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_workspace_removals"
down_revision = "20260924_drop_billing_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_removals",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("removed_by", sa.String(length=64), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_removal"),
    )
    op.create_index(op.f("ix_workspace_removals_user_id"), "workspace_removals", ["user_id"])
    op.create_index(
        op.f("ix_workspace_removals_organization_id"),
        "workspace_removals",
        ["organization_id"],
    )
    op.execute(
        "UPDATE audit_logs SET action = 'member_join' "
        "WHERE action = 'member_invite' AND metadata->>'action' = 'accepted'"
    )


def downgrade() -> None:
    op.execute("UPDATE audit_logs SET action = 'member_invite' WHERE action = 'member_join'")
    op.drop_index(op.f("ix_workspace_removals_organization_id"), "workspace_removals")
    op.drop_index(op.f("ix_workspace_removals_user_id"), "workspace_removals")
    op.drop_table("workspace_removals")
