"""A notification email is written in the language its reader chose.

The row stores an English title and message, and the email used them as they
were. An author who had chosen Spanish read "Nueva reseña" on the web page and
"New review" in the email about the same review.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models import Organization, User
from app.models.notification import Notification, NotificationChannel, NotificationType
from app.services.notification_service import NotificationService


def _notify(
    db: Session,
    user: User,
    org: Organization,
    notification_type: NotificationType,
    data: dict | None,
) -> Notification:
    with patch("app.tasks.email_tasks.send_notification_email.delay"):
        notification = NotificationService(db).create_notification(
            user_id=user.id,
            organization_id=org.id,
            notification_type=notification_type,
            title="New review",
            message="Your model 'Rutas' got a review: ★★★★",
            data=data,
            link="/workspace/models",
            channel=NotificationChannel.EMAIL,
        )
        db.commit()
    return notification


def _send(db: Session, notification: Notification) -> dict:
    from app.tasks.email_tasks import send_notification_email

    with (
        patch("app.shared.db.session.SessionLocal", return_value=db),
        patch.object(db, "close"),
        patch("app.tasks.email_tasks.EmailService.send", return_value=True) as send,
    ):
        send_notification_email(notification.id)
    assert send.call_count == 1
    return send.call_args.kwargs


@pytest.mark.parametrize(
    ("locale", "subject", "sentence"),
    [
        ("es", "Nueva reseña", "Tu modelo «Rutas» ha recibido una reseña: ★★★★"),
        ("de", "Neue Bewertung", "Ihr Modell „Rutas“ hat eine Bewertung erhalten: ★★★★"),
        (None, "New review", "Your model “Rutas” got a review: ★★★★"),
    ],
)
def test_a_review_email_is_in_the_readers_language(
    db_session: Session,
    test_user: User,
    test_organization: Organization,
    locale: str | None,
    subject: str,
    sentence: str,
) -> None:
    test_user.locale = locale
    db_session.commit()
    notification = _notify(
        db_session,
        test_user,
        test_organization,
        NotificationType.NEW_REVIEW,
        {"model_id": "mp_1", "model_name": "Rutas", "rating": 4},
    )

    sent = _send(db_session, notification)

    assert sent["subject"] == subject
    assert sentence in sent["html"]


def test_an_adoption_email_is_in_the_readers_language(
    db_session: Session, test_user: User, test_organization: Organization
) -> None:
    test_user.locale = "ca"
    db_session.commit()
    notification = _notify(
        db_session,
        test_user,
        test_organization,
        NotificationType.MODEL_ACTIVATED,
        {"model_id": "mp_1", "model_name": "Rutas"},
    )

    sent = _send(db_session, notification)

    assert sent["subject"] == "Model adoptat"
    assert "El teu model «Rutas» s’ha afegit a l’estudi d’un altre equip." in sent["html"]


def test_the_model_name_is_escaped_and_not_read_as_a_placeholder(
    db_session: Session, test_user: User, test_organization: Organization
) -> None:
    test_user.locale = "es"
    db_session.commit()
    notification = _notify(
        db_session,
        test_user,
        test_organization,
        NotificationType.NEW_REVIEW,
        {"model_name": "<b>{stars}</b>", "rating": 2},
    )

    html = _send(db_session, notification)["html"]

    assert "<b>" not in html
    assert "«&lt;b&gt;{stars}&lt;/b&gt;» ha recibido una reseña: ★★" in html


@pytest.mark.parametrize(
    ("notification_type", "data"),
    [
        (NotificationType.SYSTEM, {"trigger_id": "trg_1"}),
        (NotificationType.NEW_REVIEW, None),
        (NotificationType.NEW_REVIEW, {"model_name": "Rutas", "rating": 9}),
    ],
)
def test_an_unknown_type_or_payload_keeps_the_stored_text(
    db_session: Session,
    test_user: User,
    test_organization: Organization,
    notification_type: NotificationType,
    data: dict | None,
) -> None:
    test_user.locale = "fr"
    db_session.commit()
    notification = _notify(db_session, test_user, test_organization, notification_type, data)

    sent = _send(db_session, notification)

    assert sent["subject"] == "New review"
    assert "Your model &#x27;Rutas&#x27; got a review: ★★★★" in sent["html"]
