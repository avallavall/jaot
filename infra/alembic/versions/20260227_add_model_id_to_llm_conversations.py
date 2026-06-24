"""Add model_id column to llm_conversations table.

Revision ID: k8l9m0n1o2p3
Revises: j7k8l9m0n1o2
Create Date: 2026-02-27 10:00:00.000000+00:00

Phase 33: Wire model_id for conversation scoping per builder document.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k8l9m0n1o2p3"
down_revision: Union[str, None] = "j7k8l9m0n1o2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_conversations",
        sa.Column("model_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_llm_conversations_model_id",
        "llm_conversations",
        ["model_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_conversations_model_id", table_name="llm_conversations")
    op.drop_column("llm_conversations", "model_id")
