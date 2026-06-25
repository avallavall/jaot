"""Tests for withdrawal schedule CRUD endpoints (MKT-03)."""

import pytest
from sqlalchemy.orm import Session

from app.models import Organization, User


@pytest.fixture(autouse=True)
def _enable_monetization(enable_monetization):
    """Withdrawal schedule endpoints are paid-only; enable monetization for this module."""


class TestWithdrawalScheduleEndpoints:
    """Test withdrawal schedule CRUD endpoints via HTTP."""

    def _setup_seller(self, db_session: Session):
        """Create a seller org with bank details and a user."""
        org = Organization(
            id="sched-seller",
            name="Schedule Seller",
            credits_balance=1000,
            credits_earned=500,
            stripe_connect_onboarding_complete=True,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        user = User(
            id="sched-seller-user",
            email="sched-seller@test.com",
            name="Schedule Seller User",
            organization_id=org.id,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        return org, user

    def test_create_schedule(self, db_session: Session, client, mock_auth):
        """POST /api/v2/credits/schedules with valid data returns 200 and created schedule."""
        org, user = self._setup_seller(db_session)
        mock_auth(user)

        response = client.post(
            "/api/v2/credits/schedules",
            json={
                "frequency": "monthly",
                "amount_type": "all",
                "min_threshold": 100,
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["frequency"] == "monthly"
        assert data["amount_type"] == "all"
        assert data["is_active"] is True
        assert data["min_threshold"] == 100

    def test_list_schedules(self, db_session: Session, client, mock_auth):
        """GET /api/v2/credits/schedules returns exactly the org's own schedules."""
        org, user = self._setup_seller(db_session)
        mock_auth(user)

        create_resp = client.post(
            "/api/v2/credits/schedules",
            json={"frequency": "weekly", "amount_type": "all", "min_threshold": 50},
        )
        assert create_resp.status_code == 200
        created_id = create_resp.json()["id"]

        response = client.get("/api/v2/credits/schedules")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        schedule = data[0]
        assert schedule["id"] == created_id
        assert schedule["frequency"] == "weekly"
        assert schedule["amount_type"] == "all"
        assert schedule["min_threshold"] == 50
        assert schedule["is_active"] is True
        # Verify the schedule belongs to the test org (via DB round-trip).
        from app.models import WithdrawalSchedule

        row = db_session.query(WithdrawalSchedule).filter(WithdrawalSchedule.id == created_id).one()
        assert row.organization_id == org.id

    def test_delete_schedule(self, db_session: Session, client, mock_auth):
        """DELETE /api/v2/credits/schedules/{id} removes the schedule."""
        org, user = self._setup_seller(db_session)
        mock_auth(user)

        # Create
        create_resp = client.post(
            "/api/v2/credits/schedules",
            json={"frequency": "monthly", "amount_type": "all", "min_threshold": 100},
        )
        schedule_id = create_resp.json()["id"]

        # Delete
        del_resp = client.delete(f"/api/v2/credits/schedules/{schedule_id}")
        assert del_resp.status_code == 200

        # Verify schedule is gone (deactivated)
        list_resp = client.get("/api/v2/credits/schedules")
        active_schedules = [s for s in list_resp.json() if s["is_active"]]
        assert len(active_schedules) == 0

    def test_schedule_with_threshold(self, db_session: Session, client, mock_auth):
        """Verify schedule respects minimum payout threshold field."""
        org, user = self._setup_seller(db_session)
        mock_auth(user)

        response = client.post(
            "/api/v2/credits/schedules",
            json={
                "frequency": "biweekly",
                "amount_type": "percentage",
                "amount_value": 75.0,
                "min_threshold": 250,
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["min_threshold"] == 250
        assert data["amount_type"] == "percentage"
        assert data["amount_value"] == 75.0
        assert data["frequency"] == "biweekly"
