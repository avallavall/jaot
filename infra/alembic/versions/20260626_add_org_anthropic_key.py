"""Add encrypted per-organization Anthropic API key (BYOK)

Lets an organization store its own Anthropic API key so its LLM calls run on the
org's own account (BYOK-first) instead of the shared platform key. The value is
Fernet-encrypted at rest (see app/services/llm/byok.py) — never stored in plaintext.

Additive-only per root CLAUDE.md "Migrations" rule: one nullable ADD COLUMN, no
backfill/default, no DROP/RENAME. Pre-existing orgs keep NULL (= no BYOK, use the
platform key).

Revision ID: 20260626_org_anthropic_key
Revises: 20260611_llm_message_cost
Create Date: 2026-06-26
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260626_org_anthropic_key"
down_revision = "20260611_llm_message_cost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("anthropic_api_key_encrypted", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "anthropic_api_key_encrypted")
