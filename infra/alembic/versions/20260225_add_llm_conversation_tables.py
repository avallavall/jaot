"""Add LLM conversation and message tables.

Revision ID: i6j7k8l9m0n1
Revises: h5i6j7k8l9m0
Create Date: 2026-02-25 09:30:00.000000+00:00

LLM-01: Conversation persistence for NL-to-formulation chat.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i6j7k8l9m0n1"
down_revision: Union[str, None] = "h5i6j7k8l9m0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # LLM conversations table
    op.create_table(
        "llm_conversations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(64),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "organization_model_id",
            sa.String(64),
            sa.ForeignKey("organization_models.id"),
            nullable=True,
        ),
        sa.Column("current_formulation", sa.JSON(), nullable=True),
        sa.Column("template_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_llm_conversations_organization_id",
        "llm_conversations",
        ["organization_id"],
    )
    op.create_index(
        "ix_llm_conversations_user_id",
        "llm_conversations",
        ["user_id"],
    )
    op.create_index(
        "ix_llm_conversations_expires_at",
        "llm_conversations",
        ["expires_at"],
    )

    # LLM messages table
    op.create_table(
        "llm_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("llm_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("formulation_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_llm_messages_conversation_id",
        "llm_messages",
        ["conversation_id"],
    )
    op.create_index(
        "ix_llm_messages_conv_created",
        "llm_messages",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("llm_messages")
    op.drop_table("llm_conversations")
