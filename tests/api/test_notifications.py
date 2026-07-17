"""Tests for notification API endpoints and service."""

from app.models import Notification, NotificationChannel, NotificationType
from app.services.notification_service import NotificationService
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


class TestNotificationEndpoints:
    """Tests for notification API endpoints."""

    def test_list_notifications_requires_auth(self, client):
        """Test that listing notifications returns exactly 401 without auth."""
        response = client.get("/api/v2/notifications")
        assert response.status_code == 401
        body = response.json()
        assert body["error"] == "unauthorized"
        assert body["message"]

    def test_get_unread_count_requires_auth(self, client):
        """Test that getting unread count returns exactly 401 without auth."""
        response = client.get("/api/v2/notifications/unread-count")
        assert response.status_code == 401
        body = response.json()
        assert body["error"] == "unauthorized"
        assert body["message"]

    def test_mark_read_requires_auth(self, client):
        """Test that marking as read returns exactly 401 without auth."""
        response = client.post("/api/v2/notifications/test-id/read")
        assert response.status_code == 401
        body = response.json()
        assert body["error"] == "unauthorized"
        assert body["message"]

    def test_mark_all_read_requires_auth(self, client):
        """Test that marking all as read returns exactly 401 without auth."""
        response = client.post("/api/v2/notifications/read-all")
        assert response.status_code == 401
        body = response.json()
        assert body["error"] == "unauthorized"
        assert body["message"]


class TestNotificationService:
    """Tests for NotificationService against real PostgreSQL."""

    def test_notify_execution_completed(self, db_session, test_user, test_organization):
        """Real DB: notify_execution_completed persists row with correct payload."""
        service = NotificationService(db_session)

        notification = service.notify_execution_completed(
            user_id=test_user.id,
            organization_id=test_organization.id,
            execution_id="exec-123",
            model_name="Budget Allocation",
            objective_value=1234.56,
        )
        db_session.commit()

        # Verify row persisted via fresh query
        persisted = db_session.query(Notification).filter_by(id=notification.id).first()
        assert persisted is not None
        assert persisted.type == NotificationType.EXECUTION_COMPLETED.value
        assert persisted.user_id == test_user.id
        assert persisted.organization_id == test_organization.id
        assert persisted.is_read is False
        assert persisted.created_at is not None

        # Verify exact data payload
        assert persisted.data["execution_id"] == "exec-123"
        assert persisted.data["model_name"] == "Budget Allocation"
        assert persisted.data["objective_value"] == 1234.56

        # Verify link points at the execution
        assert persisted.link == "/solve/executions/exec-123"

        # Verify message contains formatted objective (4 decimal places per service)
        assert "Budget Allocation" in persisted.message
        assert "1234.5600" in persisted.message

    def test_notify_execution_failed(self, db_session, test_user, test_organization):
        """Real DB: notify_execution_failed persists row with error in data payload."""
        service = NotificationService(db_session)

        notification = service.notify_execution_failed(
            user_id=test_user.id,
            organization_id=test_organization.id,
            execution_id="exec-456",
            model_name="Test Model",
            error="Solver timeout",
        )
        db_session.commit()

        persisted = db_session.query(Notification).filter_by(id=notification.id).first()
        assert persisted is not None
        assert persisted.type == NotificationType.EXECUTION_FAILED.value
        assert persisted.user_id == test_user.id
        assert persisted.organization_id == test_organization.id
        assert persisted.title == "Execution Failed"
        assert persisted.is_read is False

        # Verify exact error payload preserved
        assert persisted.data["error"] == "Solver timeout"
        assert persisted.data["model_name"] == "Test Model"
        assert persisted.data["execution_id"] == "exec-456"

        # In-app channel by default (matches NotificationChannel.IN_APP)
        assert persisted.channel == NotificationChannel.IN_APP.value

    def test_get_notifications_filters_by_organization_id(
        self, db_session, test_user, test_organization, test_organization_2
    ):
        """User notifications query must filter by organization_id."""
        # Create one notification in org A and one in org B, both for user U
        notif_a = Notification(
            id=generate_id("notif_"),
            user_id=test_user.id,
            organization_id=test_organization.id,
            type=NotificationType.EXECUTION_COMPLETED.value,
            title="Org A notif",
            message="Belongs to org A",
            channel=NotificationChannel.IN_APP.value,
            created_at=utcnow().replace(tzinfo=None),
        )
        notif_b = Notification(
            id=generate_id("notif_"),
            user_id=test_user.id,
            organization_id=test_organization_2.id,
            type=NotificationType.EXECUTION_COMPLETED.value,
            title="Org B notif",
            message="Belongs to org B",
            channel=NotificationChannel.IN_APP.value,
            created_at=utcnow().replace(tzinfo=None),
        )
        db_session.add_all([notif_a, notif_b])
        db_session.commit()

        service = NotificationService(db_session)

        # Org A scope returns only the org A notification
        results_a = service.get_user_notifications(
            user_id=test_user.id, organization_id=test_organization.id
        )
        assert len(results_a) == 1
        assert results_a[0].id == notif_a.id

        # Org B scope returns only the org B notification
        results_b = service.get_user_notifications(
            user_id=test_user.id, organization_id=test_organization_2.id
        )
        assert len(results_b) == 1
        assert results_b[0].id == notif_b.id

    def test_unread_count_isolated_per_organization(
        self, db_session, test_user, test_organization, test_organization_2
    ):
        """Unread count must not leak across organizations."""
        # 2 unread notifications in org A, 3 unread in org B
        for i in range(2):
            db_session.add(
                Notification(
                    id=generate_id("notif_"),
                    user_id=test_user.id,
                    organization_id=test_organization.id,
                    type=NotificationType.EXECUTION_COMPLETED.value,
                    title=f"Org A {i}",
                    message="m",
                    is_read=False,
                    channel=NotificationChannel.IN_APP.value,
                    created_at=utcnow().replace(tzinfo=None),
                )
            )
        for i in range(3):
            db_session.add(
                Notification(
                    id=generate_id("notif_"),
                    user_id=test_user.id,
                    organization_id=test_organization_2.id,
                    type=NotificationType.EXECUTION_COMPLETED.value,
                    title=f"Org B {i}",
                    message="m",
                    is_read=False,
                    channel=NotificationChannel.IN_APP.value,
                    created_at=utcnow().replace(tzinfo=None),
                )
            )
        db_session.commit()

        service = NotificationService(db_session)
        assert service.get_unread_count(test_user.id, organization_id=test_organization.id) == 2
        assert service.get_unread_count(test_user.id, organization_id=test_organization_2.id) == 3

    def test_mark_as_read_blocks_cross_org(
        self, db_session, test_user, test_organization, test_organization_2
    ):
        """mark_as_read must reject notifications from a different org."""
        notif_b_id = generate_id("notif_")
        notif_b = Notification(
            id=notif_b_id,
            user_id=test_user.id,
            organization_id=test_organization_2.id,
            type=NotificationType.EXECUTION_COMPLETED.value,
            title="Org B notif",
            message="m",
            is_read=False,
            channel=NotificationChannel.IN_APP.value,
            created_at=utcnow().replace(tzinfo=None),
        )
        db_session.add(notif_b)
        db_session.commit()

        service = NotificationService(db_session)
        # Attempting to mark as read while scoping to org A returns None
        result = service.mark_as_read(
            notif_b_id, test_user.id, organization_id=test_organization.id
        )
        assert result is None

        # Verify the notification is still unread in DB
        db_session.refresh(notif_b)
        assert notif_b.is_read is False

        # Same call scoped to the correct org succeeds
        result_correct = service.mark_as_read(
            notif_b_id, test_user.id, organization_id=test_organization_2.id
        )
        assert result_correct is not None
        assert result_correct.id == notif_b_id

    def test_mark_all_read_only_affects_current_org(
        self, db_session, test_user, test_organization, test_organization_2
    ):
        """mark_all_as_read scoped to org A must not flip org B notifications."""
        notif_a_id = generate_id("notif_")
        notif_b_id = generate_id("notif_")
        db_session.add(
            Notification(
                id=notif_a_id,
                user_id=test_user.id,
                organization_id=test_organization.id,
                type=NotificationType.EXECUTION_COMPLETED.value,
                title="A",
                message="m",
                is_read=False,
                channel=NotificationChannel.IN_APP.value,
                created_at=utcnow().replace(tzinfo=None),
            )
        )
        db_session.add(
            Notification(
                id=notif_b_id,
                user_id=test_user.id,
                organization_id=test_organization_2.id,
                type=NotificationType.EXECUTION_COMPLETED.value,
                title="B",
                message="m",
                is_read=False,
                channel=NotificationChannel.IN_APP.value,
                created_at=utcnow().replace(tzinfo=None),
            )
        )
        db_session.commit()

        service = NotificationService(db_session)
        flipped = service.mark_all_as_read(test_user.id, organization_id=test_organization.id)
        assert flipped == 1
        db_session.commit()

        # Verify org A notification is now read
        notif_a = db_session.query(Notification).filter_by(id=notif_a_id).first()
        assert notif_a.is_read is True
        # Verify org B notification is still unread
        notif_b = db_session.query(Notification).filter_by(id=notif_b_id).first()
        assert notif_b.is_read is False

    def test_endpoint_does_not_leak_cross_org_notifications(
        self,
        authenticated_client,
        db_session,
        test_user,
        test_organization,
        test_organization_2,
    ):
        """End-to-end: GET /notifications must only return current-org notifications.

        Even if a notification row exists with this user_id but a different
        organization_id, the endpoint must filter it out.
        """
        # Plant a leak: a notification scoped to org B but with the test
        # user's id (the user actually belongs to org A via test_organization)
        leak_id = generate_id("notif_")
        leak = Notification(
            id=leak_id,
            user_id=test_user.id,
            organization_id=test_organization_2.id,
            type=NotificationType.EXECUTION_COMPLETED.value,
            title="LEAK from org B",
            message="should never appear",
            is_read=False,
            channel=NotificationChannel.IN_APP.value,
            created_at=utcnow().replace(tzinfo=None),
        )
        # And one legitimately in the user's actual org
        legit_id = generate_id("notif_")
        legit = Notification(
            id=legit_id,
            user_id=test_user.id,
            organization_id=test_organization.id,
            type=NotificationType.EXECUTION_COMPLETED.value,
            title="Legit",
            message="should appear",
            is_read=False,
            channel=NotificationChannel.IN_APP.value,
            created_at=utcnow().replace(tzinfo=None),
        )
        db_session.add_all([leak, legit])
        db_session.commit()

        response = authenticated_client.get("/api/v2/notifications")
        assert response.status_code == 200
        body = response.json()

        ids = {item["id"] for item in body["items"]}
        assert legit_id in ids, "legitimate notification should be returned"
        assert leak_id not in ids, "cross-org notification leaked through endpoint"
        assert body["total"] == 1
        assert body["unread_count"] == 1
