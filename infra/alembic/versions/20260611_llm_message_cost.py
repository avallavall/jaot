"""Add real token-usage + cost columns to llm_messages (W17)

Backend-audit W17: actual Anthropic token usage/cost per conversation was
never recorded — only a flat PSS credit charge and a pre-call output
estimation existed, so LLM COGS per customer was invisible.

Adds three nullable columns to llm_messages:
- input_tokens  (Integer)      — real prompt tokens from the API response
- output_tokens (Integer)      — real completion tokens
- cost_eur      (Numeric 12,6) — EUR cost priced via the
  LLM_MODEL_PRICING_EUR_PER_MTOK platform setting at persist time

Additive-only per root CLAUDE.md "Migrations" rule — three ADD COLUMN
(all nullable, no backfill, no defaults), no DROP/RENAME/type changes.
Pre-existing rows keep NULL (their usage was never captured and cannot be
reconstructed).

Revision ID: 20260611_llm_message_cost
Revises: 20260516_add_contact_messages
Create Date: 2026-06-11
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260611_llm_message_cost"
down_revision = "20260516_add_contact_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_messages", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("llm_messages", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column("llm_messages", sa.Column("cost_eur", sa.Numeric(12, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_messages", "cost_eur")
    op.drop_column("llm_messages", "output_tokens")
    op.drop_column("llm_messages", "input_tokens")
