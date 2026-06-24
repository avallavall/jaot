"""
Celery tasks for webhook delivery.

Webhooks are delivered asynchronously to avoid blocking the main execution flow.
Failed deliveries are retried up to 3 times with exponential backoff.
"""

import logging
from typing import Any

from app.services.webhook_service import deliver_webhook
from app.shared.core.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(  # type: ignore[misc]
    name="app.tasks.webhook_tasks.deliver_webhook_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,  # 30s, then 60s, then 120s (exponential)
)
def deliver_webhook_task(
    self: Any, url: str, payload: dict[str, Any], secret: str | None = None
) -> dict[str, Any]:
    """
    Deliver a webhook payload asynchronously.

    Args:
        url: The webhook endpoint URL.
        payload: The JSON payload to send.
        secret: Optional HMAC-SHA256 signing secret.
    """
    try:
        success = deliver_webhook(url=url, payload=payload, secret=secret)
        if success:
            return {"status": "delivered", "url": url, "event": payload.get("event")}
        else:
            raise Exception("Webhook delivery failed (non-2xx response)")
    except Exception as exc:
        logger.warning(
            f"Webhook delivery attempt {self.request.retries + 1} failed for {url}: {exc}"
        )
        raise self.retry(exc=exc, countdown=30 * (2**self.request.retries)) from exc
