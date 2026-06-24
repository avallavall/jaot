"""Balance reconciliation service (D-24, D-25, FIN-09).

Provides a single run_reconciliation() method used by both the Celery beat task
and the admin manual trigger endpoint. Do NOT duplicate this logic elsewhere.
"""

import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CreditTransaction, Organization

logger = logging.getLogger(__name__)


class ReconciliationService:
    """Reconciles SUM(CreditTransactions) against credits_balance for all orgs."""

    def __init__(self, db: Session):
        self.db = db

    def run_reconciliation(self) -> dict[str, Any]:
        """Reconcile all organizations' credits_balance against transaction sums.

        Returns:
            Dict with checked count, discrepancy count, and details list.
        """
        txn_sums = (
            self.db.query(
                CreditTransaction.organization_id,
                func.sum(CreditTransaction.credits_amount).label("computed_balance"),
            )
            .group_by(CreditTransaction.organization_id)
            .all()
        )

        discrepancies: list[dict[str, Any]] = []
        checked = 0

        for org_id, computed_balance in txn_sums:
            org = self.db.query(Organization).filter(Organization.id == org_id).first()
            if not org:
                continue

            checked += 1
            computed = int(computed_balance or 0)
            actual = org.credits_balance

            if computed != actual:
                discrepancy = {
                    "organization_id": org_id,
                    "computed_balance": computed,
                    "actual_balance": actual,
                    "difference": actual - computed,
                }
                discrepancies.append(discrepancy)
                logger.error(
                    "RECONCILIATION DISCREPANCY: org=%s, computed=%d, actual=%d, diff=%d",
                    org_id,
                    computed,
                    actual,
                    actual - computed,
                )

        # Also check orgs with NO transactions but non-zero balance
        # (orgs that had direct balance manipulation without CreditTransaction)
        orgs_with_balance = (
            self.db.query(Organization).filter(Organization.credits_balance != 0).all()
        )
        org_ids_with_txns = {org_id for org_id, _ in txn_sums}
        for org in orgs_with_balance:
            if org.id not in org_ids_with_txns:
                # Org has balance but zero transactions -- might be initial seeded balance
                # Only flag if balance is not the default (100)
                if org.credits_balance != 100:
                    checked += 1
                    discrepancy = {
                        "organization_id": org.id,
                        "computed_balance": 0,
                        "actual_balance": org.credits_balance,
                        "difference": org.credits_balance,
                        "note": "No CreditTransaction records found (possible seed data)",
                    }
                    discrepancies.append(discrepancy)
                    logger.warning(
                        "RECONCILIATION NOTE: org=%s has balance=%d "
                        "but no CreditTransaction records",
                        org.id,
                        org.credits_balance,
                    )

        result = {
            "checked": checked,
            "discrepancies": len(discrepancies),
            "details": discrepancies,
        }

        if discrepancies:
            logger.error(
                "Reconciliation found %d discrepancies out of %d orgs",
                len(discrepancies),
                checked,
            )
        else:
            logger.info(
                "Reconciliation clean: %d orgs checked, 0 discrepancies",
                checked,
            )

        return result
