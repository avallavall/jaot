"""Add credit idempotency constraint and low_credits_notified flag

Adds a partial unique index on credit_transactions (reference_type, reference_id)
for idempotency enforcement, and a low_credits_notified boolean on organizations
for one-shot low-balance notification tracking.

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "k2l3m4n5o6p7"
down_revision = "j1k2l3m4n5o6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add partial unique index for idempotency on credit_transactions
    # Scoped to (org, txn_type, ref_type, ref_id) to allow legitimate
    # multi-party transactions (e.g., marketplace buyer+seller+commission)
    op.create_index(
        "uq_credit_txn_reference",
        "credit_transactions",
        ["organization_id", "transaction_type", "reference_type", "reference_id"],
        unique=True,
        postgresql_where=sa.text("reference_type IS NOT NULL AND reference_id IS NOT NULL"),
    )

    # Add low_credits_notified flag to organizations
    op.add_column(
        "organizations",
        sa.Column("low_credits_notified", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )

    # Backfill existing rows
    op.execute("UPDATE organizations SET low_credits_notified = false WHERE low_credits_notified IS NULL")

    # Make non-nullable after backfill
    op.alter_column("organizations", "low_credits_notified", nullable=False)


def downgrade() -> None:
    op.drop_column("organizations", "low_credits_notified")
    op.drop_index("uq_credit_txn_reference", table_name="credit_transactions")
