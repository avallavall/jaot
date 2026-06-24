"""Add media and rich description columns to model_catalog

Revision ID: g8h9i0j1k2l3
Revises: f7g8h9i0j1k2
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "g8h9i0j1k2l3"
down_revision = "f7g8h9i0j1k2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Media columns
    op.add_column("model_catalog", sa.Column("logo_url", sa.String(length=500), nullable=True))
    op.add_column("model_catalog", sa.Column("screenshot_urls", sa.JSON(), nullable=True))

    # Rich description sections (markdown stored as text)
    op.add_column("model_catalog", sa.Column("section_overview", sa.Text(), nullable=True))
    op.add_column("model_catalog", sa.Column("section_features", sa.Text(), nullable=True))
    op.add_column("model_catalog", sa.Column("section_how_it_works", sa.Text(), nullable=True))
    op.add_column("model_catalog", sa.Column("section_example_io", sa.Text(), nullable=True))
    op.add_column("model_catalog", sa.Column("section_changelog", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_catalog", "section_changelog")
    op.drop_column("model_catalog", "section_example_io")
    op.drop_column("model_catalog", "section_how_it_works")
    op.drop_column("model_catalog", "section_features")
    op.drop_column("model_catalog", "section_overview")
    op.drop_column("model_catalog", "screenshot_urls")
    op.drop_column("model_catalog", "logo_url")
