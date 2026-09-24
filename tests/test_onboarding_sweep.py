"""The onboarding emails after day 0 are sent by an hourly sweep.

They were queued at signup with a countdown of up to 14 days. A worker holds
such a message unacknowledged until it is due, and RabbitMQ closes a channel
that holds one longer than ``consumer_timeout`` (30 minutes by default). The
Celery worker treats that as an unrecoverable error and shuts down, so the
generic worker restarted every 30 minutes while any onboarding email waited,
and the tasks it was running at that moment ran again. A user who deleted
their account in those 14 days still got the later emails.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from app.models import Organization, User
from app.shared.utils.datetime_helpers import utcnow

#: RabbitMQ's default consumer_timeout.
_CONSUMER_TIMEOUT_SECONDS = 30 * 60


def _user(
    db: Session,
    org: Organization,
    suffix: str,
    age: timedelta,
    *,
    last_day: int | None = None,
    active: bool = True,
    locale: str | None = None,
) -> User:
    user = User(
        id=f"user_onb_{suffix}",
        email=f"onb-{suffix}@example.com",
        name=f"Onb {suffix}",
        organization_id=org.id,
        is_active=active,
        locale=locale,
        created_at=utcnow() - age,
        onboarding_last_day=last_day,
    )
    db.add(user)
    db.commit()
    return user


def _sweep(db: Session) -> list[dict]:
    from app.tasks.email_tasks import send_due_onboarding_emails

    with (
        patch("app.shared.db.session.SessionLocal", return_value=db),
        patch.object(db, "close"),
        patch("app.tasks.email_tasks.send_onboarding_email.delay") as delay,
    ):
        send_due_onboarding_emails()
    return [c.kwargs for c in delay.call_args_list]


# CONTRACT-TEST: nothing onboarding queues waits in the broker past consumer_timeout.
def test_signup_queues_no_message_that_waits_past_the_consumer_timeout() -> None:
    from app.tasks.email_tasks import schedule_onboarding_sequence

    with patch("app.tasks.email_tasks.send_onboarding_email") as task:
        task.apply_async = MagicMock()
        schedule_onboarding_sequence(user_email="new@example.com", user_name="New", locale="es")

    assert task.apply_async.call_count == 1
    call = task.apply_async.call_args.kwargs
    assert call["kwargs"]["day"] == 0
    assert call["kwargs"]["locale"] == "es"
    assert call.get("countdown", 0) < _CONSUMER_TIMEOUT_SECONDS
    assert call.get("eta") is None


def test_each_user_gets_the_email_that_is_due(
    db_session: Session, test_organization: Organization
) -> None:
    _user(db_session, test_organization, "new", timedelta(hours=5))
    day1 = _user(db_session, test_organization, "d1", timedelta(days=1, hours=1))
    day3 = _user(db_session, test_organization, "d3", timedelta(days=3, hours=1), last_day=1)
    _user(db_session, test_organization, "wait", timedelta(days=2), last_day=1)

    sent = {(s["user_email"], s["day"]) for s in _sweep(db_session)}

    assert sent == {(day1.email, 1), (day3.email, 3)}
    db_session.refresh(day1)
    db_session.refresh(day3)
    assert (day1.onboarding_last_day, day3.onboarding_last_day) == (1, 3)


def test_a_second_sweep_sends_nothing_again(
    db_session: Session, test_organization: Organization
) -> None:
    _user(db_session, test_organization, "twice", timedelta(days=1, hours=1))

    assert len(_sweep(db_session)) == 1
    assert _sweep(db_session) == []


def test_a_late_user_gets_only_the_latest_email(
    db_session: Session, test_organization: Organization
) -> None:
    user = _user(db_session, test_organization, "late", timedelta(days=14, hours=3), last_day=1)

    assert [(s["user_email"], s["day"]) for s in _sweep(db_session)] == [(user.email, 14)]


def test_old_or_inactive_accounts_get_nothing(
    db_session: Session, test_organization: Organization
) -> None:
    _user(db_session, test_organization, "off", timedelta(days=3, hours=1), active=False)
    _user(db_session, test_organization, "old", timedelta(days=40))
    _user(db_session, test_organization, "done", timedelta(days=15), last_day=14)

    assert _sweep(db_session) == []


def test_the_email_uses_the_current_name_and_language(
    db_session: Session, test_organization: Organization
) -> None:
    user = _user(db_session, test_organization, "lang", timedelta(days=1, hours=1), locale="en")
    user.locale = "ca"
    user.name = "Nom Nou"
    db_session.commit()

    (sent,) = _sweep(db_session)

    assert (sent["user_name"], sent["locale"]) == ("Nom Nou", "ca")


def test_a_refused_queue_leaves_the_email_due(
    db_session: Session, test_organization: Organization
) -> None:
    from app.tasks.email_tasks import send_due_onboarding_emails

    user = _user(db_session, test_organization, "broker", timedelta(days=1, hours=1))
    with (
        patch("app.shared.db.session.SessionLocal", return_value=db_session),
        patch.object(db_session, "close"),
        patch(
            "app.tasks.email_tasks.send_onboarding_email.delay",
            side_effect=ConnectionError("broker down"),
        ),
    ):
        summary = send_due_onboarding_emails()

    assert summary == {"queued": 0, "errors": 1}
    db_session.refresh(user)
    assert user.onboarding_last_day is None
    assert [s["day"] for s in _sweep(db_session)] == [1]


def test_the_sweep_is_on_the_beat_schedule() -> None:
    from app.shared.core.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule["send-due-onboarding-emails"]
    assert schedule["task"] == "send_due_onboarding_emails"
    assert schedule["schedule"] <= 3600
