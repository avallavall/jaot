"""Add narrow partial unique index on refund-on-solve-task credit transactions.

Phase 6.1 / DEBT-01 (CR-01). Belt-and-suspenders alongside the existing
uq_credit_txn_reference partial unique index (migration k2l3m4n5o6p7).
This narrower index makes the "one refund per solve task" invariant
explicit and greppable from schema audit tooling.

Scope: credit_transactions rows where transaction_type='refund' AND
reference_type='solve_task'. Any INSERT producing a second such row
for the same (organization_id, reference_id=task_id) will raise
IntegrityError, which CreditsService.record_transaction already handles
via its except IntegrityError path (app/services/credits_service.py:297-315).

Additive-only (CLAUDE.md): CREATE INDEX only. No schema rewrite, no DROP,
no RENAME. Reversible via downgrade() DROP INDEX. No data backfill.

Pre-flight audit query (operator runs BEFORE alembic upgrade):
    SELECT organization_id, reference_id, COUNT(*) AS n
    FROM credit_transactions
    WHERE transaction_type = 'refund'
      AND reference_type = 'solve_task'
      AND reference_id IS NOT NULL
    GROUP BY organization_id, reference_id
    HAVING COUNT(*) > 1;
If the query returns rows, the migration will fail until duplicates
are reconciled. Historical reconciliation is out of scope for 6.1 (D-15).

Revision ID: 20260418_refund_unique
Revises: 20260416_solver_name
Create Date: 2026-04-18
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260418_refund_unique"
down_revision = "20260416_solver_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ux_credit_txn_refund_solve_task",
        "credit_transactions",
        ["organization_id", "reference_id"],
        unique=True,
        postgresql_where=sa.text(
            "transaction_type = 'refund' "
            "AND reference_type = 'solve_task' "
            "AND reference_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_credit_txn_refund_solve_task",
        table_name="credit_transactions",
    )
