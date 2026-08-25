"""A notification email is queued, never sent inside the request.

Three shapes this code has had. It marked ``email_sent = True`` and sent
nothing, so the one row anybody would check lied. Then it sent inline, which
put up to ``SMTP_TIMEOUT`` seconds of somebody else's mail server in front of
the reader who triggered it — for an email that is no part of what they did.
Now a worker sends it, and only after the row it describes is committed.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models import Organization, User
from app.models.notification import NotificationChannel, NotificationType
from app.services.notification_service import NotificationService

pytestmark = pytest.mark.contract


# CONTRACT-TEST: nothing reaches the mail server from inside the request.
def test_no_smtp_call_happens_on_the_request_path(
    db_session: Session, test_user: User, test_organization: Organization
) -> None:
    with (
        patch("app.services.email_service.EmailService.send") as send,
        patch("app.tasks.email_tasks.send_notification_email.delay") as delay,
    ):
        NotificationService(db_session).create_notification(
            user_id=test_user.id,
            organization_id=test_organization.id,
            notification_type=NotificationType.MODEL_ACTIVATED,
            title="Your model was adopted",
            message="Somebody added it to their studio.",
            channel=NotificationChannel.EMAIL,
        )
        assert send.call_count == 0, "the request path talked to the mail server"
        # Not queued yet either — the row is only flushed at this point.
        assert delay.call_count == 0, "queued before the row was committed"

        db_session.commit()
        assert delay.call_count == 1, "the job was never queued after the commit"


# CONTRACT-TEST: a caller that rolls back queues no email.
def test_a_rolled_back_notification_sends_nothing(
    db_session: Session, test_user: User, test_organization: Organization
) -> None:
    with patch("app.tasks.email_tasks.send_notification_email.delay") as delay:
        NotificationService(db_session).create_notification(
            user_id=test_user.id,
            organization_id=test_organization.id,
            notification_type=NotificationType.MODEL_ACTIVATED,
            title="Never happened",
            message="The transaction did not survive.",
            channel=NotificationChannel.EMAIL,
        )
        db_session.rollback()
        assert delay.call_count == 0, "queued an email for a row that was rolled back"


# CONTRACT-TEST: the flag is written by whoever actually sent the message.
#
# `email_sent` is the only place anybody can find out whether the email went.
# It must not be set by the code that merely asked for it.
def test_the_sent_flag_is_not_set_by_the_request(
    db_session: Session, test_user: User, test_organization: Organization
) -> None:
    with patch("app.tasks.email_tasks.send_notification_email.delay"):
        notification = NotificationService(db_session).create_notification(
            user_id=test_user.id,
            organization_id=test_organization.id,
            notification_type=NotificationType.MODEL_ACTIVATED,
            title="Your model was adopted",
            message="Somebody added it to their studio.",
            channel=NotificationChannel.EMAIL,
        )
        assert notification.email_sent is False, "the request claimed the email had been sent"
