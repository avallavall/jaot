"""Add formulation_ratings table for LLM feedback collection.

Revision ID: m9n0o1p2q3r4
Revises: k8l9m0n1o2p3
Create Date: 2026-02-27 22:00:00.000000+00:00

Phase 31: Feedback collection — formulation rating model.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m9n0o1p2q3r4"
down_revision: Union[str, None] = "k8l9m0n1o2p3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "formulation_ratings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("llm_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.String(64),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("rating", sa.String(10), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("zone", sa.String(20), nullable=False),
        sa.Column("formulation_snapshot", postgresql.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("conversation_id", "user_id", name="uq_rating_conv_user"),
    )


def downgrade() -> None:
    op.drop_table("formulation_ratings")
