"""Add locale to users

Revision ID: c3d4e5f6g7h8
Revises: w8x9y0z1a2b3
Create Date: 2026-03-05
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3d4e5f6g7h8"
down_revision = "w8x9y0z1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locale", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locale")
