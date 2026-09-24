"""Keep the AI spend of deleted conversations in the monthly budget.

The monthly budget sums ``llm_messages.cost_eur``, and those rows go with their
conversation. Deleting a conversation (any API key can) or an account took that
spend off the month, so chatting and deleting could run the platform's
Anthropic bill past its budget without end.

``llm_retained_spend`` receives the cost before the rows are deleted. It has no
link to a user or an organization, so an account erased under GDPR leaves an
amount and a date and nothing that points at the person.

Additive and reversible: the downgrade drops a table nothing else reads. Spend
retained while it existed stops counting after a downgrade.

Revision ID: 20260924_llm_retained_spend
Revises: 20260924_mask_secret_audit
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_llm_retained_spend"
down_revision = "20260924_mask_secret_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_retained_spend",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("spent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost_eur", sa.Numeric(12, 6), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_retained_spend_spent_at", "llm_retained_spend", ["spent_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_retained_spend_spent_at", table_name="llm_retained_spend")
    op.drop_table("llm_retained_spend")
