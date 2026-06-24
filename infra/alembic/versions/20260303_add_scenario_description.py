"""Add scenario_description to model_catalog

Revision ID: v7w8x9y0z1a2
Revises: p1q2r3s4t5u6
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "v7w8x9y0z1a2"
down_revision = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_catalog", sa.Column("scenario_description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_catalog", "scenario_description")
