"""Add FK constraint on organizations.owner_user_id -> users.id.

Revision ID: a3b4c5d6e7f8
Revises: k2l3m4n5o6p7
Create Date: 2026-03-17
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a3b4c5d6e7f8"
down_revision = "k2l3m4n5o6p7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # First: clean up any orphan references where owner_user_id
    # points to a user that no longer exists in the users table.
    # Without this, the FK constraint creation would fail.
    op.execute(
        """
        UPDATE organizations
        SET owner_user_id = NULL
        WHERE owner_user_id IS NOT NULL
          AND owner_user_id NOT IN (SELECT id FROM users)
        """
    )
    # Then: add the FK constraint
    op.create_foreign_key(
        "fk_org_owner_user",
        "organizations",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_org_owner_user", "organizations", type_="foreignkey")
