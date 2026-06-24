"""Public contact-form submission endpoint (Phase 9, D-06).

POST /api/v2/contact accepts an anonymous-or-authenticated form submission,
persists a durable ``contact_messages`` row, and enqueues a Celery task for
SMTP delivery. The endpoint is in ``PUBLIC_PATHS`` so it bypasses strict
auth; the middleware still attempts opportunistic non-fatal auth so
signed-in submissions auto-tag ``user_id`` / ``organization_id``.

Layered guards (in handler order):
    1. Honeypot (D-01)
    2. Rate-limit 3 / 15 min per IP (D-02)
    3. Rate-limit 10 / day per IP   (D-02)
    4. CRLF strip on subject        (T-09-02 mitigation)
    5. Pydantic validation runs FIRST, in the framework — failures are
       routed to ``contact_validation_exception_handler`` defined below.
"""

import ipaddress
import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.deps import DBSession, OptionalCurrentOrg, OptionalCurrentUser
from app.models.contact_message import ContactMessage
from app.schemas.contact import ContactCreate, ContactResponse
from app.shared.core.prometheus_metrics import CONTACT_SPAM_BLOCKED
from app.shared.core.rate_limiter import check_rate_limit, check_rate_limit_15min
from app.shared.utils.request_helpers import get_client_ip
from app.tasks.contact_tasks import send_contact_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["contact"])


def _redact_ip(ip: str | None) -> str:
    """Mask IPv4 to /24 and IPv6 to /48 for log-aggregator GDPR safety (T-09-09)."""
    if not ip:
        return "unknown"
    try:
        parsed = ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        return "unknown"
    if isinstance(parsed, ipaddress.IPv4Address):
        network = ipaddress.IPv4Network(f"{parsed}/24", strict=False)
        return f"{network.network_address}".rsplit(".", 1)[0] + ".X"
    network = ipaddress.IPv6Network(f"{parsed}/48", strict=False)
    return f"{network.network_address}/48"


def _log_submission(
    result: str,
    *,
    client_ip: str | None,
    signed_in: bool,
    message_id: str | None = None,
    **extras: object,
) -> None:
    """Single source of truth for the `contact_submission` structured log shape."""
    logger.info(
        "contact_submission",
        extra={
            "message_id": message_id,
            "result": result,
            "ip_redacted": _redact_ip(client_ip),
            "signed_in": signed_in,
            **extras,
        },
    )


@router.post("", response_model=ContactResponse, status_code=status.HTTP_200_OK)
def submit_contact(
    payload: ContactCreate,
    request: Request,
    db: DBSession,
    user: OptionalCurrentUser,
    org: OptionalCurrentOrg,
) -> ContactResponse:
    """Submit a public contact-form message.

    Anonymous submissions persist with NULL ``user_id`` / ``organization_id``.
    Signed-in submissions auto-tag the row via the opportunistic-auth branch
    in :class:`app.shared.core.auth_middleware.ASGIAuthMiddleware` (Phase 9
    Task 1b). The response intentionally echoes only id/status/created_at —
    never user-supplied content (T-09-06 privacy minimum).
    """
    client_ip = get_client_ip(request)
    signed_in = user is not None

    # 1. Honeypot — must run before any DB or rate-limit work (D-01 / T-09-01).
    if payload.website is not None and payload.website.strip() != "":
        CONTACT_SPAM_BLOCKED.labels(reason="honeypot").inc()
        _log_submission("honeypot", client_ip=client_ip, signed_in=signed_in)
        raise HTTPException(status_code=400, detail="Bad request")

    # 2. Rate-limit (3 / 15 min) — D-02 tighter than the global public limit.
    # Distinct key suffix from the day-cap below: in the in-memory fallback both
    # checks share `_memory_store[key]`, so a shared key would double-count
    # each request and trip the 15-min limit one POST early.
    allowed_15min, rate_info_15min = check_rate_limit_15min(f"contact_ip_15min:{client_ip}", 3)
    if not allowed_15min:
        CONTACT_SPAM_BLOCKED.labels(reason="rate_limit_minute").inc()
        _log_submission("rate_limited", client_ip=client_ip, signed_in=signed_in, window="15min")
        raise HTTPException(status_code=429, detail=rate_info_15min)

    # 3. Rate-limit (10 / day) — D-02. Permissive per-minute cap so the daily counter
    # is the only effective gate at this step; the 15-min gate already fired above.
    allowed_day, rate_info_day = check_rate_limit(
        f"contact_ip_day:{client_ip}", limit_per_minute=999_999, limit_per_day=10
    )
    if not allowed_day:
        CONTACT_SPAM_BLOCKED.labels(reason="rate_limit_day").inc()
        _log_submission("rate_limited", client_ip=client_ip, signed_in=signed_in, window="day")
        raise HTTPException(status_code=429, detail=rate_info_day)

    # 4. T-09-02: strip CR/LF so a malicious subject cannot inject email headers.
    subject = payload.subject.replace("\r", "").replace("\n", " ").strip()

    # 5. Persist (D-03) — auto-tag user/org if the middleware attached them (D-06).
    msg = ContactMessage(
        name=payload.name,
        email=payload.email,
        subject=subject,
        body=payload.message,
        locale=payload.locale,
        user_id=user.id if user is not None else None,
        organization_id=org.id if org is not None else None,
        ip_address=client_ip,
        status="pending",
        attempts=0,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    _log_submission("accepted", client_ip=client_ip, signed_in=signed_in, message_id=msg.id)

    # 6. Enqueue delivery with message_id ONLY (T-09-10 — no PII through broker).
    send_contact_email.delay(message_id=msg.id)

    return ContactResponse.model_validate(msg)


async def contact_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Scoped 422 handler that emits a structured log only for /api/v2/contact.

    For any other request path, delegates to FastAPI's default validation
    handler so the standard 422 shape is preserved everywhere else (I3 fix:
    the handler owns its own scope check — global registration is safe).

    On /api/v2/contact validation failures:
      - Increments ``CONTACT_SPAM_BLOCKED{reason="validation"}``.
      - Logs a ``validation_error`` line containing ONLY field locations and
        Pydantic error type codes — never user-supplied values (T-09-09).
      - Returns the standard FastAPI 422 response shape.
    """
    if not request.url.path.startswith("/api/v2/contact"):
        return await request_validation_exception_handler(request, exc)

    CONTACT_SPAM_BLOCKED.labels(reason="validation").inc()
    logger.info(
        "validation_error",
        extra={
            "path": request.url.path,
            "errors": [
                {"loc": list(err.get("loc", [])), "type": err.get("type")} for err in exc.errors()
            ],
        },
    )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})
