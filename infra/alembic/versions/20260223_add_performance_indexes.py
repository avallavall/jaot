"""Add performance indexes for credit_transactions and api_keys.

Revision ID: h5i6j7k8l9m0
Revises: g4h5i6j7k8l9
Create Date: 2026-02-23 19:00:00.000000+00:00

DATA-03: Compound index on credit_transactions(organization_id, created_at)
DATA-04: Index on api_keys.organization_id
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h5i6j7k8l9m0"
down_revision: Union[str, None] = "g4h5i6j7k8l9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # DATA-03: Compound index for credit transaction queries by org + date range
    op.create_index(
        "ix_credit_txn_org_created",
        "credit_transactions",
        ["organization_id", "created_at"],
    )

    # DATA-04: Index for admin API key listing by organization
    op.create_index(
        "ix_api_keys_organization_id",
        "api_keys",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_keys_organization_id", table_name="api_keys")
    op.drop_index("ix_credit_txn_org_created", table_name="credit_transactions")
