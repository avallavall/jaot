"""Add tos_accepted_at to users

Revision ID: a1b2c3d4e5f6
Revises: v7w8x9y0z1a2
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "w8x9y0z1a2b3"
down_revision = "v7w8x9y0z1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("tos_accepted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "tos_accepted_at")
