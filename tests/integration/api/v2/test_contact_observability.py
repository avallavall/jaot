"""Observability regression tests for the contact-form subsystem — Phase 9 Wave 2.

Locks in the contract between production counters/structured logs and the
operator tooling (Prometheus alert selectors + runbook). Drift on either side
breaks alerts silently in production.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from unittest.mock import patch

import yaml
from prometheus_client import REGISTRY

from app.api.v2.contact import _redact_ip
from app.models.contact_message import ContactMessage
from app.tasks.contact_tasks import send_contact_email

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_ALERT_RULES_PATH = _PROJECT_ROOT / "monitoring" / "prometheus" / "alert_rules.yml"

# Closed-vocabulary label values for the contact counters. Alert selectors
# MUST reference only these values — drift would silently disable an alert.
_EXPECTED_LABELS: dict[str, dict[str, set[str]]] = {
    "jaot_contact_message_send_attempts_total": {
        "result": {"sent", "retry", "failed"},
    },
    "jaot_contact_spam_blocked_total": {
        "reason": {"honeypot", "rate_limit_minute", "rate_limit_day", "validation"},
    },
}

_PII_NAME = "John Doe"
_PII_EMAIL = "john.pii@example.com"
_PII_SUBJECT = "My secret subject XYZZY"
_PII_BODY = "My secret body with PII payload PLUGH"

_SELECTOR_RE = re.compile(r"(jaot_contact_[a-z0-9_]+)\{([^}]*)\}")
_LABEL_PAIR_RE = re.compile(r'([a-z_][a-z0-9_]*)="([^"]*)"')


def test_alert_rule_label_selector_matches_counter():
    """Every contact_form alert selector references a real counter label value."""
    assert _ALERT_RULES_PATH.exists(), f"alert_rules.yml missing at {_ALERT_RULES_PATH}"

    rules_yaml = yaml.safe_load(_ALERT_RULES_PATH.read_text(encoding="utf-8"))
    groups = rules_yaml.get("groups", [])
    contact_group = next((g for g in groups if g.get("name") == "contact_form"), None)
    assert contact_group is not None, "alert_rules.yml is missing the contact_form group"

    rules = contact_group.get("rules", [])
    assert len(rules) >= 2, "contact_form group must have at least 2 alert rules"

    found_triples: list[tuple[str, str, str]] = []
    for rule in rules:
        expr = rule.get("expr", "")
        for metric_match in _SELECTOR_RE.finditer(expr):
            metric = metric_match.group(1)
            label_block = metric_match.group(2)
            for label_match in _LABEL_PAIR_RE.finditer(label_block):
                found_triples.append((metric, label_match.group(1), label_match.group(2)))

    # At least one selector found (the ContactFormDeliveryFailing rule has
    # `jaot_contact_message_send_attempts_total{result="failed"}`).
    assert any(
        t[0] == "jaot_contact_message_send_attempts_total" and t[1] == "result"
        for t in found_triples
    ), "no selector references jaot_contact_message_send_attempts_total{result=...}"

    # Every selector must resolve against the expected vocabulary.
    for metric, label, value in found_triples:
        assert metric in _EXPECTED_LABELS, (
            f"alert references unknown metric {metric!r} — add to _EXPECTED_LABELS "
            "or correct the alert expression"
        )
        expected_for_label = _EXPECTED_LABELS[metric].get(label)
        assert expected_for_label is not None, (
            f"alert references {metric}{{{label}=...}} but counter does not emit that label"
        )
        assert value in expected_for_label, (
            f'alert references {metric}{{{label}="{value}"}} — counter only emits '
            f"{label} ∈ {sorted(expected_for_label)}"
        )


def test_submission_log_redacts_pii(client, caplog):
    """The ``contact_submission`` log line must redact every user-supplied value."""
    caplog.set_level(logging.INFO, logger="app.api.v2.contact")
    payload = {
        "name": _PII_NAME,
        "email": _PII_EMAIL,
        "subject": _PII_SUBJECT,
        "message": _PII_BODY,
        "website": "",
        "locale": "en",
    }

    with patch("app.tasks.contact_tasks.send_contact_email.delay"):
        resp = client.post("/api/v2/contact", json=payload)

    assert resp.status_code == 200, resp.text
    assert "contact_submission" in caplog.text, (
        "expected contact_submission log line on accepted submission — "
        "logger.info call site missing in submit_contact happy path"
    )

    for pii in (_PII_NAME, _PII_EMAIL, _PII_SUBJECT, _PII_BODY):
        assert pii not in caplog.text, (
            f"PII leak: {pii!r} appears in caplog.text — submit_contact "
            "is logging a user-supplied field; redact at the call site (T-09-09)"
        )

    # And the structured `result` value MUST be `accepted` for the happy path.
    # caplog.records lets us assert on extra fields, not just the rendered text.
    submission_records = [r for r in caplog.records if r.message == "contact_submission"]
    assert any(getattr(r, "result", None) == "accepted" for r in submission_records), (
        "no contact_submission record carries extra={'result': 'accepted'}"
    )


def _validation_counter_value() -> float:
    """Return the current value of CONTACT_SPAM_BLOCKED{reason='validation'} via public API."""
    return (
        REGISTRY.get_sample_value("jaot_contact_spam_blocked_total", {"reason": "validation"})
        or 0.0
    )


def test_validation_error_emission_end_to_end(client, caplog):
    """422 path emits ``validation_error`` log + bumps CONTACT_SPAM_BLOCKED{reason='validation'}."""
    caplog.set_level(logging.INFO, logger="app.api.v2.contact")
    before_metric = _validation_counter_value()

    bad_email_payload = {
        "name": _PII_NAME,
        "email": "notanemail",
        "subject": _PII_SUBJECT,
        "message": _PII_BODY,
        "website": "",
        "locale": "en",
    }

    resp = client.post("/api/v2/contact", json=bad_email_payload)

    assert resp.status_code == 422, resp.text
    assert "validation_error" in caplog.text, (
        "scoped contact_validation_exception_handler did not emit `validation_error` — "
        "either the handler is not registered on app.main or path-scope check skipped it"
    )

    after_metric = _validation_counter_value()
    assert after_metric == before_metric + 1, (
        f"CONTACT_SPAM_BLOCKED{{reason='validation'}} did not increment: "
        f"before={before_metric}, after={after_metric}"
    )

    for pii in (_PII_NAME, _PII_SUBJECT, _PII_BODY, "notanemail"):
        assert pii not in caplog.text, (
            f"PII leak in validation handler: {pii!r} appears in caplog.text — "
            "the handler should log ONLY field locations + Pydantic error types"
        )


def test_send_attempt_log_redacts_pii(db_session, caplog):
    """``contact_send_attempt`` log line must redact every user-supplied value."""
    caplog.set_level(logging.INFO, logger="app.tasks.contact_tasks")

    # Insert a row directly so we can invoke the task synchronously without
    # depending on Celery's queue infrastructure.
    msg = ContactMessage(
        name=_PII_NAME,
        email=_PII_EMAIL,
        subject=_PII_SUBJECT,
        body=_PII_BODY,
        locale="en",
        user_id=None,
        organization_id=None,
        ip_address="1.2.3.4",
        status="pending",
        attempts=0,
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)

    # Patch EmailService.send to a no-op success so the happy path runs.
    with patch("app.tasks.contact_tasks.EmailService.send", return_value=True):
        result = send_contact_email.apply(args=[msg.id]).get()

    assert result["status"] == "sent"
    assert "contact_send_attempt" in caplog.text, (
        "expected contact_send_attempt log line — logger.info call site "
        "missing in send_contact_email after the sent branch"
    )

    for pii in (_PII_NAME, _PII_EMAIL, _PII_SUBJECT, _PII_BODY):
        assert pii not in caplog.text, (
            f"PII leak in send-attempt log: {pii!r} appears in caplog.text — "
            "redact at the logger.info call site (T-09-09)"
        )

    send_attempt_records = [r for r in caplog.records if r.message == "contact_send_attempt"]
    assert any(getattr(r, "result", None) == "sent" for r in send_attempt_records), (
        "no contact_send_attempt record carries extra={'result': 'sent'}"
    )


def test_ip_redact_helper():
    """Direct unit test of the _redact_ip helper used by submit_contact."""
    # IPv4 — last octet masked.
    assert _redact_ip("1.2.3.4") == "1.2.3.X"
    assert _redact_ip("192.168.1.255") == "192.168.1.X"
    assert _redact_ip("10.0.0.1") == "10.0.0.X"

    # IPv6 — first /48 preserved, rest masked. Exact form is implementation
    # choice but MUST NOT echo back the full address.
    redacted_v6 = _redact_ip("2001:db8::1")
    assert redacted_v6 != "2001:db8::1", "IPv6 _redact_ip must not echo the full address back"
    assert "2001" in redacted_v6 and "db8" in redacted_v6, (
        f"IPv6 redaction lost the /48 prefix: {redacted_v6!r}"
    )

    # Invalid input → "unknown" (no exception, no leak).
    assert _redact_ip("not-an-ip") == "unknown"
    assert _redact_ip("") == "unknown"
    assert _redact_ip("999.999.999.999") == "unknown"
