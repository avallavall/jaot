"""
Celery tasks for webhook delivery.

Webhooks are delivered asynchronously to avoid blocking the main execution flow.
Failed deliveries are retried up to 3 times with exponential backoff.

When the caller passes a ``run_id``, every attempt and the final outcome are
written onto that ``TriggerRun``. Until that existed, ``webhook_attempts`` and
``webhook_delivered`` were columns nobody wrote: the Run History table's Webhook
column always read "—", the admin panel's webhook delivery rate was computed
from an empty set, and a webhook that never arrived was invisible to everyone.
"""

import logging
from typing import Any

from app.services.webhook_service import deliver_webhook
from app.shared.core.celery_app import celery_app
from app.shared.utils.validators import blocked_url_target

logger = logging.getLogger(__name__)


def _record_attempt(run_id: str | None, *, delivered: bool | None, counts: bool = True) -> None:
    """Count this attempt on the run, and record the outcome when it is settled.

    ``counts=False`` writes the verdict without bumping the counter, for the one
    case that settles without ever contacting the endpoint: an address the
    server refuses to call. Counting that as an attempt tells the owner their
    endpoint was tried once and did not answer, which is the opposite of what
    happened.

    ``delivered`` is None while attempts remain: the count goes up, the verdict
    stays open. It becomes True on a 2xx and False once the retries are spent.

    Never lets a bookkeeping failure sink the delivery: the payload arriving
    matters more than the column, and the caller is a retrying Celery task whose
    own exception path means something else.
    """
    if not run_id:
        return
    from app.models.trigger import TriggerRun  # noqa: PLC0415
    from app.shared.db.session import SessionLocal  # noqa: PLC0415

    db = SessionLocal()
    try:
        run = db.query(TriggerRun).filter(TriggerRun.id == run_id).first()
        if run is None:
            return
        if counts:
            run.webhook_attempts = (run.webhook_attempts or 0) + 1
        if delivered is not None:
            run.webhook_delivered = delivered
        db.commit()
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not fail the task
        logger.warning("Could not record the webhook attempt on run %s: %s", run_id, exc)
        db.rollback()
    finally:
        db.close()


def _notify_delivery_failed(run_id: str | None, url: str, reason: str | None = None) -> None:
    """Tell the person who owns the trigger that the result never arrived.

    ``reason`` replaces the "after N attempts" sentence when the attempts are
    not the story — an address the server refuses to call is settled on the
    first look, and counting to four before saying so tells the owner to check
    their endpoint when the endpoint was never contacted.
    """
    if not run_id:
        return
    from app.models import NotificationType  # noqa: PLC0415
    from app.models.trigger import SolveTrigger, TriggerRun  # noqa: PLC0415
    from app.services.notification_service import NotificationService  # noqa: PLC0415
    from app.shared.db.session import SessionLocal  # noqa: PLC0415

    db = SessionLocal()
    try:
        run = db.query(TriggerRun).filter(TriggerRun.id == run_id).first()
        if run is None:
            return
        trigger = db.query(SolveTrigger).filter(SolveTrigger.id == run.trigger_id).first()
        if trigger is None or not trigger.created_by:
            return
        NotificationService(db).create_notification(
            user_id=trigger.created_by,
            organization_id=trigger.organization_id,
            notification_type=NotificationType.SYSTEM,
            title="Webhook delivery failed",
            # The trigger name is always the subject of the sentence, whichever
            # ending it gets: a notification that does not say WHICH trigger
            # sends the owner looking through all of them.
            message=f"The result of '{trigger.name}' "
            + (
                reason
                or (
                    f"could not be delivered to {url} after {run.webhook_attempts} "
                    f"attempts. The run itself finished; only the delivery failed."
                )
            ),
            data={"trigger_id": trigger.id, "run_id": run.id, "webhook_url": url},
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001 — a missing notification must not mask the failure
        logger.warning("Could not notify the owner of run %s: %s", run_id, exc)
        db.rollback()
    finally:
        db.close()


def _fail(task: Any, run_id: str | None, url: str, exc: Exception, *, last_attempt: bool) -> None:
    """Record this failed attempt, tell the owner if it was the last, then retry.

    Never returns: it always raises, either the retry signal or the failure
    itself once the retries are spent.
    """
    _record_attempt(run_id, delivered=False if last_attempt else None)
    logger.warning(f"Webhook delivery attempt {task.request.retries + 1} failed for {url}: {exc}")
    if last_attempt:
        _notify_delivery_failed(run_id, url)
    raise task.retry(exc=exc, countdown=30 * (2**task.request.retries)) from exc


@celery_app.task(  # type: ignore[misc]
    name="app.tasks.webhook_tasks.deliver_webhook_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,  # 30s, then 60s, then 120s (exponential)
)
def deliver_webhook_task(
    self: Any,
    url: str,
    payload: dict[str, Any],
    secret: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Deliver a webhook payload asynchronously.

    Args:
        url: The webhook endpoint URL.
        payload: The JSON payload to send.
        secret: Optional HMAC-SHA256 signing secret.
        run_id: The TriggerRun this delivery belongs to, so the attempt count and
            the outcome are written where the Run History table reads them.
    """
    # An address the server will not call is a settled answer, not a bad
    # moment: waiting cannot change where a hostname resolves to. Retried like
    # a timeout it spent four attempts over seven minutes and then told the
    # owner their endpoint had not answered — while nothing had ever been sent
    # to it. Same rule the create form applies, from the same function, asked
    # here for a different decision: whether to try again.
    #
    # A hostname that does not resolve is deliberately NOT settled. It may
    # resolve by the next attempt, which is what the retries are for.
    blocked = blocked_url_target(url)
    if blocked is not None:
        _record_attempt(run_id, delivered=False, counts=False)
        logger.warning("Webhook for %s points at %s — refusing to deliver", url, blocked)
        _notify_delivery_failed(
            run_id,
            url,
            reason=(
                f"could not be sent to {url}: that address resolves to {blocked}, "
                f"which is private, loopback or link-local, so the server will not "
                f"call it. The run itself finished. Point the webhook at a public "
                f"address to receive it."
            ),
        )
        return {"status": "refused", "url": url, "address": blocked}

    # Celery re-raises the original exception instead of MaxRetriesExceededError
    # whenever ``retry(exc=...)`` is given one, so the last try has to be
    # recognised by counting, not by catching.
    last_attempt = self.request.retries >= self.max_retries

    try:
        success = deliver_webhook(url=url, payload=payload, secret=secret)
    except Exception as exc:
        _fail(self, run_id, url, exc, last_attempt=last_attempt)

    if success:
        _record_attempt(run_id, delivered=True)
        return {"status": "delivered", "url": url, "event": payload.get("event")}

    _fail(
        self,
        run_id,
        url,
        Exception("Webhook delivery failed (non-2xx response)"),
        last_attempt=last_attempt,
    )
