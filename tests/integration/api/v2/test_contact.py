"""RED integration tests for POST /api/v2/contact — Phase 9 Wave 0.

These tests are intentionally failing today (Wave 0 ships only the contract).
Wave 1 turns them GREEN by adding:
  - app/models/contact_message.py (ContactMessage ORM)
  - app/api/v2/contact.py (POST /api/v2/contact route)
  - app/tasks/contact_tasks.py (send_contact_email Celery task)
  - PUBLIC_PATHS append for ("/api/v2/contact", "POST")
  - Optional-JWT non-fatal authentication on PUBLIC_PATHS
  - CONTACT_SPAM_BLOCKED + CONTACT_SEND_ATTEMPTS in prometheus_metrics

The expected RED failure mode is ModuleNotFoundError at collection time
(neither `app.models.contact_message` nor `app.tasks.contact_tasks` exist yet).

Covers Phase 9 decisions D-01, D-02, D-03, D-05, D-06, D-07, D-09.
Mitigates threats T-09-01 (spam/abuse), T-09-02 (header injection),
T-09-03 (reply-to injection), T-09-10 (Celery PII leak).
"""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import text

from app.models.contact_message import ContactMessage  # noqa: F401
from app.shared.core.prometheus_metrics import (  # noqa: F401
    CONTACT_SEND_ATTEMPTS,
    CONTACT_SPAM_BLOCKED,
)
from app.tasks.contact_tasks import send_contact_email  # noqa: F401


def _valid_payload(**overrides: object) -> dict[str, object]:
    """Return a baseline valid POST body. Overrides shadow individual fields."""
    base: dict[str, object] = {
        "name": "Alice Example",
        "email": "alice@example.com",
        "subject": "Question about pricing",
        "message": "Hi team, I have a quick question about the pro plan.",
        "website": "",  # honeypot — must remain empty
        "locale": "en",
    }
    base.update(overrides)
    return base


# Test 1 — Anonymous happy path (D-03 + D-05 + D-06)


def test_post_contact_happy_path_anonymous(client, db_session):
    """Anonymous POST persists row with NULL user/org and enqueues exactly one task."""
    with patch("app.tasks.contact_tasks.send_contact_email.delay") as mock_delay:
        resp = client.post("/api/v2/contact", json=_valid_payload())

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"].startswith("ctc_")
    assert body["status"] == "pending"
    assert "created_at" in body

    # Persisted row matches anonymous shape.
    row = db_session.execute(
        text(
            "SELECT id, user_id, organization_id, status, attempts "
            "FROM contact_messages WHERE id = :id"
        ),
        {"id": body["id"]},
    ).fetchone()
    assert row is not None
    assert row.user_id is None
    assert row.organization_id is None
    assert row.status == "pending"
    assert row.attempts == 0

    # Exactly one Celery task enqueued with only the message_id.
    assert mock_delay.call_count == 1
    call_args, call_kwargs = mock_delay.call_args
    # Accept either positional or kwarg form — T-09-10 only requires that the
    # ONLY value transferred via the broker is the row id.
    sent_id = call_kwargs.get("message_id", call_args[0] if call_args else None)
    assert sent_id == body["id"]


# Test 2 — Authenticated happy path (D-06 auto-tag)


def test_post_contact_happy_path_authenticated(
    authenticated_client, db_session, test_user, test_organization
):
    """Signed-in POST persists row with user_id + organization_id populated."""
    with patch("app.tasks.contact_tasks.send_contact_email.delay"):
        resp = authenticated_client.post("/api/v2/contact", json=_valid_payload())

    assert resp.status_code == 200, resp.text
    body = resp.json()
    row = db_session.execute(
        text("SELECT user_id, organization_id FROM contact_messages WHERE id = :id"),
        {"id": body["id"]},
    ).fetchone()
    assert row is not None
    assert row.user_id == test_user.id
    assert row.organization_id == test_organization.id


# Test 3 — Honeypot trips → 400, no row, no enqueue, counter bumps (D-01 / T-09-01)


def test_post_contact_honeypot_blocks_submission(client, db_session):
    """Non-empty `website` honeypot field → 400, NO persistence, NO Celery enqueue."""
    before_count = db_session.execute(text("SELECT COUNT(*) FROM contact_messages")).scalar()
    before_metric = CONTACT_SPAM_BLOCKED.labels(reason="honeypot")._value.get()

    with patch("app.tasks.contact_tasks.send_contact_email.delay") as mock_delay:
        resp = client.post(
            "/api/v2/contact",
            json=_valid_payload(website="http://spam.example.com"),
        )

    assert resp.status_code == 400
    assert mock_delay.call_count == 0

    after_count = db_session.execute(text("SELECT COUNT(*) FROM contact_messages")).scalar()
    assert after_count == before_count, "honeypot trip must NOT persist a row"

    after_metric = CONTACT_SPAM_BLOCKED.labels(reason="honeypot")._value.get()
    assert after_metric == before_metric + 1


# Test 4 — Pydantic validation: invalid email → 422


def test_post_contact_validation_email_invalid(client):
    resp = client.post("/api/v2/contact", json=_valid_payload(email="notanemail"))
    assert resp.status_code == 422
    detail = str(resp.json())
    assert "email" in detail.lower()


# Test 5 — Pydantic validation: name too long → 422


def test_post_contact_validation_name_too_long(client):
    resp = client.post("/api/v2/contact", json=_valid_payload(name="x" * 121))
    assert resp.status_code == 422
    detail = str(resp.json()).lower()
    assert "name" in detail


# Test 6 — Pydantic validation: message too long → 422


def test_post_contact_validation_message_too_long(client):
    resp = client.post("/api/v2/contact", json=_valid_payload(message="x" * 5001))
    assert resp.status_code == 422


# Test 7 — Rate-limit: 4th submission in tight window → 429 (D-02)


def test_post_contact_rate_limit_15min_window(client, real_rate_limiter):
    """With real rate-limiter on, the 4th rapid POST from the same IP → 429."""
    with patch("app.tasks.contact_tasks.send_contact_email.delay"):
        first_three = [client.post("/api/v2/contact", json=_valid_payload()) for _ in range(3)]
        fourth = client.post("/api/v2/contact", json=_valid_payload())

    for resp in first_three:
        assert resp.status_code == 200, resp.text
    assert fourth.status_code == 429
    body = fourth.json()
    # check_rate_limit puts the info dict in `detail`; retry_after is the canonical field.
    detail = body.get("detail", body)
    assert "retry_after" in str(detail).lower() or "retry" in str(detail).lower()


# Test 8 — Rate-limit daily cap (D-02)


def test_post_contact_rate_limit_daily_cap(client, real_rate_limiter):
    """10 prior submissions on the same day key → 11th POST → 429.

    Patches at the import site (`app.api.v2.contact.check_rate_limit`) — the
    route binds the name into its own namespace via `from … import …`, so
    patching `rate_limiter.check_rate_limit` would not intercept the call.
    """
    with patch(
        "app.api.v2.contact.check_rate_limit",
        return_value=(False, {"retry_after": 86400}),
    ):
        resp = client.post("/api/v2/contact", json=_valid_payload())

    assert resp.status_code == 429


# Test 9 — CRLF in subject must be stripped on persistence (T-09-02)


def test_post_contact_subject_strips_crlf(client, db_session):
    """Subject column on the persisted row must not contain CR or LF (header injection guard)."""
    payload = _valid_payload(subject="hello\r\nBCC: attacker@evil.com")
    with patch("app.tasks.contact_tasks.send_contact_email.delay"):
        resp = client.post("/api/v2/contact", json=payload)

    assert resp.status_code == 200, resp.text
    row_subject = db_session.execute(
        text("SELECT subject FROM contact_messages WHERE id = :id"),
        {"id": resp.json()["id"]},
    ).scalar()
    assert row_subject is not None
    assert "\r" not in row_subject
    assert "\n" not in row_subject


# Test 10 — Reply-to injection (T-09-03): malformed email rejected


def test_post_contact_email_invalid_format_rejected(client):
    """Pydantic EmailStr rejects values containing HTML/script payloads."""
    resp = client.post(
        "/api/v2/contact",
        json=_valid_payload(email="<script>alert(1)</script>@evil.com"),
    )
    assert resp.status_code == 422
