"""
Webhook delivery service for outbound event notifications.

Sends HTTP POST requests to organization-configured webhook URLs
when async jobs complete, credits change, etc.

Webhook payloads are signed with HMAC-SHA256 using the organization's
webhook_secret, delivered via the X-Jaot-Signature header.
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT = 10.0  # seconds
WEBHOOK_USER_AGENT = "JAOT-Webhook/1.0"


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Create HMAC-SHA256 signature for a webhook payload."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


def build_webhook_payload(
    event_type: str,
    data: dict[str, Any],
    organization_id: str,
) -> dict[str, Any]:
    """Build a standardized webhook payload."""
    return {
        "event": event_type,
        "timestamp": utcnow().isoformat() + "Z",
        "organization_id": organization_id,
        "data": data,
    }


def deliver_webhook(
    url: str,
    payload: dict[str, Any],
    secret: str | None = None,
) -> bool:
    """
    Deliver a webhook payload to a URL.

    Args:
        url: The webhook endpoint URL.
        payload: The JSON payload to send.
        secret: Optional HMAC-SHA256 signing secret.

    Returns:
        True if delivery succeeded (2xx response), False otherwise.
    """
    from app.shared.utils.validators import validate_url_not_private

    try:
        validate_url_not_private(url)
    except ValueError as e:
        logger.warning("SSRF blocked: %s", e)
        return False

    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": WEBHOOK_USER_AGENT,
        "X-Jaot-Event": payload.get("event", "unknown"),
        "X-Jaot-Delivery-Timestamp": str(int(time.time())),
    }

    if secret:
        signature = _sign_payload(payload_bytes, secret)
        headers["X-Jaot-Signature"] = f"sha256={signature}"

    try:
        with httpx.Client(timeout=WEBHOOK_TIMEOUT) as client:
            resp = client.post(url, content=payload_bytes, headers=headers)

        if 200 <= resp.status_code < 300:
            logger.info(f"Webhook delivered to {url}: {payload.get('event')} ({resp.status_code})")
            return True
        logger.warning(f"Webhook delivery failed to {url}: {resp.status_code} {resp.text[:200]}")
        return False

    except httpx.TimeoutException:
        logger.warning(f"Webhook delivery timed out to {url}")
        return False
    except (httpx.HTTPError, OSError) as e:
        logger.error(f"Webhook delivery error to {url}: {e}")
        return False


def execution_completed_event(
    organization_id: str,
    execution_id: str,
    model_name: str,
    status: str,
    objective_value: float | None = None,
    execution_time_ms: int | None = None,
    credits_consumed: int = 0,
) -> dict[str, Any]:
    """Build an execution.completed webhook payload."""
    return build_webhook_payload(
        event_type="execution.completed",
        organization_id=organization_id,
        data={
            "execution_id": execution_id,
            "model_name": model_name,
            "status": status,
            "objective_value": objective_value,
            "execution_time_ms": execution_time_ms,
            "credits_consumed": credits_consumed,
        },
    )


def execution_failed_event(
    organization_id: str,
    execution_id: str,
    model_name: str,
    error_message: str,
) -> dict[str, Any]:
    """Build an execution.failed webhook payload."""
    return build_webhook_payload(
        event_type="execution.failed",
        organization_id=organization_id,
        data={
            "execution_id": execution_id,
            "model_name": model_name,
            "error_message": error_message,
        },
    )


def credits_low_event(
    organization_id: str,
    current_balance: int,
    threshold: int,
) -> dict[str, Any]:
    """Build a credits.low webhook payload."""
    return build_webhook_payload(
        event_type="credits.low",
        organization_id=organization_id,
        data={
            "current_balance": current_balance,
            "threshold": threshold,
        },
    )
