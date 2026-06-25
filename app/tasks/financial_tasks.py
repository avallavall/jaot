"""Celery tasks for scheduled financial operations.

- process_scheduled_withdrawals: Execute due scheduled withdrawals (D-27, FIN-06)
- run_balance_reconciliation: Verify SUM(transactions) == credits_balance (D-24, D-25, FIN-09)

IMPORTANT: Reconciliation logic lives in ReconciliationService. This task is a thin
Celery wrapper -- do NOT duplicate reconciliation logic here.
"""

import logging
from typing import Any

from app.shared.core.celery_app import celery_app
from app.shared.db.session import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="process_scheduled_withdrawals", acks_late=True)
def process_scheduled_withdrawals_task(self: Any) -> dict[str, Any]:
    """Process all due scheduled withdrawals (D-27, FIN-06).

    Called by Celery beat on a daily schedule. Finds all active WithdrawalSchedule
    records where next_execution <= now() and creates Withdrawal records.
    """
    db = SessionLocal()
    try:
        from app.services.platform_settings_service import PlatformSettingsService

        # Withdrawals are a monetization-only feature. In the free, collaborative
        # deployment (MONETIZATION_ENABLED=false) there is nothing to pay out, so
        # skip the run entirely rather than scanning for due schedules.
        if not PlatformSettingsService.is_monetization_enabled(db):
            logger.info("Scheduled withdrawals skipped: monetization disabled")
            return {"processed": 0, "withdrawal_ids": [], "skipped": "monetization_disabled"}

        from app.services.credits_service import CreditsService

        service = CreditsService(db)
        withdrawals = service.process_scheduled_withdrawals()
        db.commit()

        result = {
            "processed": len(withdrawals),
            "withdrawal_ids": [w.id for w in withdrawals],
        }
        logger.info("Scheduled withdrawals processed: %s", result)
        return result
    except Exception as e:
        logger.error("Scheduled withdrawal processing failed: %s", e)
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="run_balance_reconciliation", acks_late=True)
def run_balance_reconciliation_task(self: Any) -> dict[str, Any]:
    """Reconcile SUM(CreditTransactions) against credits_balance (D-24, D-25, FIN-09).

    Delegates to ReconciliationService.run_reconciliation() -- no logic duplication.
    """
    db = SessionLocal()
    try:
        from app.services.reconciliation_service import ReconciliationService

        service = ReconciliationService(db)
        return service.run_reconciliation()
    except Exception as e:
        logger.error("Reconciliation task failed: %s", e)
        raise
    finally:
        db.close()
