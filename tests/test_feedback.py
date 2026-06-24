"""Tests for feedback endpoints: LLM rating, admin analytics."""

from datetime import timedelta

import pytest

from app.models.formulation_rating import FormulationRating
from app.models.llm_conversation import LLMConversation
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


@pytest.fixture
def test_conversation(db_session, test_user, test_organization):
    """Create a non-expired LLM conversation for the test user."""
    conv = LLMConversation(
        id=generate_id("conv_"),
        organization_id=test_organization.id,
        user_id=test_user.id,
        created_at=utcnow().replace(tzinfo=None),
        expires_at=(utcnow() + timedelta(hours=24)).replace(tzinfo=None),
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    return conv


@pytest.fixture
def test_conversation_with_formulation(db_session, test_user, test_organization):
    """Create a conversation with a current_formulation set."""
    conv = LLMConversation(
        id=generate_id("conv_"),
        organization_id=test_organization.id,
        user_id=test_user.id,
        current_formulation={"variables": [{"name": "x"}], "objective": "max x"},
        created_at=utcnow().replace(tzinfo=None),
        expires_at=(utcnow() + timedelta(hours=24)).replace(tzinfo=None),
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    return conv


def _create_rating(
    db_session,
    conversation_id,
    user_id,
    org_id,
    rating="up",
    zone="llm",
    comment=None,
    created_at=None,
):
    """Helper to create a FormulationRating directly in the DB."""
    r = FormulationRating(
        id=generate_id("frt_"),
        conversation_id=conversation_id,
        user_id=user_id,
        organization_id=org_id,
        rating=rating,
        zone=zone,
        comment=comment,
        created_at=created_at or utcnow().replace(tzinfo=None),
        updated_at=created_at or utcnow().replace(tzinfo=None),
    )
    db_session.add(r)
    db_session.commit()
    return r


def _make_conv(db_session, user_id, org_id):
    """Helper to create a minimal conversation."""
    conv = LLMConversation(
        id=generate_id("conv_"),
        organization_id=org_id,
        user_id=user_id,
        created_at=utcnow().replace(tzinfo=None),
        expires_at=(utcnow() + timedelta(hours=24)).replace(tzinfo=None),
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    return conv


class TestFormulationRating:
    """POST/GET /api/v2/feedback/conversations/{id}/rating tests."""

    def test_rate_up(self, authenticated_client, test_conversation):
        """POST rating 'up' returns 200 with correct fields."""
        resp = authenticated_client.post(
            f"/api/v2/feedback/conversations/{test_conversation.id}/rating",
            json={"rating": "up", "zone": "llm"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rating"] == "up"
        assert data["zone"] == "llm"
        assert data["conversation_id"] == test_conversation.id
        assert data["comment"] is None

    def test_rate_down_with_comment(self, authenticated_client, test_conversation):
        """POST 'down' with comment stores and returns the comment."""
        resp = authenticated_client.post(
            f"/api/v2/feedback/conversations/{test_conversation.id}/rating",
            json={
                "rating": "down",
                "zone": "llm",
                "comment": "The formulation was incorrect",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rating"] == "down"
        assert data["comment"] == "The formulation was incorrect"

    def test_rate_with_formulation_snapshot(
        self, authenticated_client, test_conversation_with_formulation
    ):
        """POST with formulation_snapshot dict is stored correctly."""
        snapshot = {"variables": [{"name": "x"}], "objective": "max x"}
        resp = authenticated_client.post(
            f"/api/v2/feedback/conversations/{test_conversation_with_formulation.id}/rating",
            json={
                "rating": "up",
                "zone": "builder",
                "formulation_snapshot": snapshot,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["formulation_snapshot"] == snapshot

    def test_rerate_overwrites(self, authenticated_client, db_session, test_conversation):
        """Re-rating same conversation overwrites (UPSERT), not duplicates."""
        # First rating: up
        resp1 = authenticated_client.post(
            f"/api/v2/feedback/conversations/{test_conversation.id}/rating",
            json={"rating": "up", "zone": "llm"},
        )
        assert resp1.status_code == 200
        assert resp1.json()["rating"] == "up"
        rating_id = resp1.json()["id"]

        # Second rating: down — should overwrite
        resp2 = authenticated_client.post(
            f"/api/v2/feedback/conversations/{test_conversation.id}/rating",
            json={"rating": "down", "zone": "llm", "comment": "changed my mind"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["rating"] == "down"
        assert resp2.json()["comment"] == "changed my mind"
        assert resp2.json()["id"] == rating_id  # same record

        # Verify only one record exists
        count = (
            db_session.query(FormulationRating)
            .filter(FormulationRating.conversation_id == test_conversation.id)
            .count()
        )
        assert count == 1

    def test_rate_nonexistent_conversation(self, authenticated_client):
        """POST to unknown conversation returns 404."""
        resp = authenticated_client.post(
            "/api/v2/feedback/conversations/conv_nonexistent/rating",
            json={"rating": "up", "zone": "llm"},
        )
        assert resp.status_code == 404

    def test_rate_invalid_zone(self, authenticated_client, test_conversation):
        """POST with invalid zone returns 422."""
        resp = authenticated_client.post(
            f"/api/v2/feedback/conversations/{test_conversation.id}/rating",
            json={"rating": "up", "zone": "invalid"},
        )
        assert resp.status_code == 422

    def test_rate_invalid_rating_value(self, authenticated_client, test_conversation):
        """POST with rating 'maybe' returns 422."""
        resp = authenticated_client.post(
            f"/api/v2/feedback/conversations/{test_conversation.id}/rating",
            json={"rating": "maybe", "zone": "llm"},
        )
        assert resp.status_code == 422

    def test_get_rating(self, authenticated_client, test_conversation):
        """GET returns the rating that was POSTed."""
        authenticated_client.post(
            f"/api/v2/feedback/conversations/{test_conversation.id}/rating",
            json={"rating": "up", "zone": "llm", "comment": "great"},
        )

        resp = authenticated_client.get(
            f"/api/v2/feedback/conversations/{test_conversation.id}/rating"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rating"] == "up"
        assert data["comment"] == "great"

    def test_get_rating_not_found(self, authenticated_client, test_conversation):
        """GET with no rating returns 404."""
        resp = authenticated_client.get(
            f"/api/v2/feedback/conversations/{test_conversation.id}/rating"
        )
        assert resp.status_code == 404


class TestZoneTagging:
    """Zone validation and persistence tests."""

    def test_zone_persisted(self, authenticated_client, db_session, test_conversation):
        """POST with zone='builder' persists the zone value."""
        resp = authenticated_client.post(
            f"/api/v2/feedback/conversations/{test_conversation.id}/rating",
            json={"rating": "up", "zone": "builder"},
        )
        assert resp.status_code == 200

        record = (
            db_session.query(FormulationRating)
            .filter(FormulationRating.conversation_id == test_conversation.id)
            .first()
        )
        assert record is not None
        assert record.zone == "builder"

    def test_all_valid_zones(self, authenticated_client, db_session, test_user, test_organization):
        """All 6 valid zones are accepted."""
        valid_zones = ["builder", "solver", "llm", "results", "dashboard", "models"]
        for zone_name in valid_zones:
            conv = _make_conv(db_session, test_user.id, test_organization.id)
            resp = authenticated_client.post(
                f"/api/v2/feedback/conversations/{conv.id}/rating",
                json={"rating": "up", "zone": zone_name},
            )
            assert resp.status_code == 200, f"Zone '{zone_name}' should be accepted"
            assert resp.json()["zone"] == zone_name


class TestAdminFeedback:
    """Admin feedback list and stats endpoints."""

    def test_list_feedback_empty(self, admin_client):
        """GET /admin/feedback with no data returns empty items."""
        resp = admin_client.get("/api/v2/admin/feedback")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_feedback_with_data(self, admin_client, db_session, test_user, test_organization):
        """GET /admin/feedback returns items when data exists."""
        convs = [_make_conv(db_session, test_user.id, test_organization.id) for _ in range(3)]
        for conv in convs:
            _create_rating(db_session, conv.id, test_user.id, test_organization.id)

        resp = admin_client.get("/api/v2/admin/feedback")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    def test_list_feedback_filter_by_zone(
        self, admin_client, db_session, test_user, test_organization
    ):
        """Filter by zone returns only matching ratings."""
        conv1 = _make_conv(db_session, test_user.id, test_organization.id)
        conv2 = _make_conv(db_session, test_user.id, test_organization.id)
        _create_rating(db_session, conv1.id, test_user.id, test_organization.id, zone="llm")
        _create_rating(db_session, conv2.id, test_user.id, test_organization.id, zone="builder")

        resp = admin_client.get("/api/v2/admin/feedback?zone=llm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["zone"] == "llm"

    def test_list_feedback_filter_by_rating(
        self, admin_client, db_session, test_user, test_organization
    ):
        """Filter by rating returns only up or down ratings."""
        conv1 = _make_conv(db_session, test_user.id, test_organization.id)
        conv2 = _make_conv(db_session, test_user.id, test_organization.id)
        _create_rating(db_session, conv1.id, test_user.id, test_organization.id, rating="up")
        _create_rating(db_session, conv2.id, test_user.id, test_organization.id, rating="down")

        resp = admin_client.get("/api/v2/admin/feedback?rating=up")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["rating"] == "up"

    def test_list_feedback_pagination(self, admin_client, db_session, test_user, test_organization):
        """Pagination with page_size=2 on 5 items returns correct pages."""
        convs = [_make_conv(db_session, test_user.id, test_organization.id) for _ in range(5)]
        for conv in convs:
            _create_rating(db_session, conv.id, test_user.id, test_organization.id)

        resp = admin_client.get("/api/v2/admin/feedback?page_size=2&page=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["pages"] == 3  # ceil(5/2)

    def test_feedback_stats_empty(self, admin_client):
        """GET /admin/feedback/stats with no data returns zeros."""
        resp = admin_client.get("/api/v2/admin/feedback/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["up"] == 0
        assert data["down"] == 0
        assert data["avg_rating"] == 0.0
        assert data["by_zone"] == []
        assert data["daily_trend"] == []

    def test_feedback_stats_with_data(self, admin_client, db_session, test_user, test_organization):
        """Stats correctly count up/down, by_zone, avg_rating, and daily_trend."""
        conv1 = _make_conv(db_session, test_user.id, test_organization.id)
        conv2 = _make_conv(db_session, test_user.id, test_organization.id)
        conv3 = _make_conv(db_session, test_user.id, test_organization.id)
        _create_rating(
            db_session, conv1.id, test_user.id, test_organization.id, rating="up", zone="llm"
        )
        _create_rating(
            db_session, conv2.id, test_user.id, test_organization.id, rating="up", zone="llm"
        )
        _create_rating(
            db_session, conv3.id, test_user.id, test_organization.id, rating="down", zone="builder"
        )

        resp = admin_client.get("/api/v2/admin/feedback/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["up"] == 2
        assert data["down"] == 1
        # avg_rating = 2/3 ~ 0.6667
        assert abs(data["avg_rating"] - 0.6667) < 0.01

        # by_zone should have 2 entries
        zones = {z["zone"]: z for z in data["by_zone"]}
        assert "llm" in zones
        assert zones["llm"]["total"] == 2
        assert zones["llm"]["up"] == 2
        assert "builder" in zones
        assert zones["builder"]["total"] == 1
        assert zones["builder"]["down"] == 1

        # daily_trend should be non-empty
        assert len(data["daily_trend"]) >= 1
        # Today's trend entry should show totals
        trend_total = sum(d["total"] for d in data["daily_trend"])
        assert trend_total == 3

    def test_feedback_stats_avg_rating_all_up(
        self, admin_client, db_session, test_user, test_organization
    ):
        """All up ratings produce avg_rating == 1.0."""
        for _ in range(3):
            conv = _make_conv(db_session, test_user.id, test_organization.id)
            _create_rating(
                db_session, conv.id, test_user.id, test_organization.id, rating="up", zone="llm"
            )

        resp = admin_client.get("/api/v2/admin/feedback/stats")
        assert resp.status_code == 200
        assert resp.json()["avg_rating"] == 1.0

    def test_feedback_stats_avg_rating_empty(self, admin_client):
        """No ratings produce avg_rating == 0.0."""
        resp = admin_client.get("/api/v2/admin/feedback/stats")
        assert resp.status_code == 200
        assert resp.json()["avg_rating"] == 0.0

    def test_feedback_stats_daily_trend(
        self, admin_client, db_session, test_user, test_organization
    ):
        """Daily trend has entries for different days, sorted ascending."""
        today = utcnow().replace(tzinfo=None)
        yesterday = today - timedelta(days=1)

        conv1 = _make_conv(db_session, test_user.id, test_organization.id)
        conv2 = _make_conv(db_session, test_user.id, test_organization.id)
        _create_rating(
            db_session,
            conv1.id,
            test_user.id,
            test_organization.id,
            rating="up",
            zone="llm",
            created_at=yesterday,
        )
        _create_rating(
            db_session,
            conv2.id,
            test_user.id,
            test_organization.id,
            rating="down",
            zone="llm",
            created_at=today,
        )

        resp = admin_client.get("/api/v2/admin/feedback/stats")
        assert resp.status_code == 200
        data = resp.json()
        trend = data["daily_trend"]
        assert len(trend) == 2

        # Sorted ascending: yesterday first
        assert trend[0]["date"] == yesterday.date().isoformat()
        assert trend[0]["total"] == 1
        assert trend[0]["up"] == 1
        assert trend[0]["down"] == 0

        assert trend[1]["date"] == today.date().isoformat()
        assert trend[1]["total"] == 1
        assert trend[1]["up"] == 0
        assert trend[1]["down"] == 1

    def test_feedback_stats_filter_by_zone(
        self, admin_client, db_session, test_user, test_organization
    ):
        """Zone filter narrows stats including daily_trend."""
        conv1 = _make_conv(db_session, test_user.id, test_organization.id)
        conv2 = _make_conv(db_session, test_user.id, test_organization.id)
        _create_rating(
            db_session, conv1.id, test_user.id, test_organization.id, rating="up", zone="llm"
        )
        _create_rating(
            db_session, conv2.id, test_user.id, test_organization.id, rating="down", zone="builder"
        )

        resp = admin_client.get("/api/v2/admin/feedback/stats?zone=llm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["up"] == 1
        assert data["down"] == 0
        assert len(data["by_zone"]) == 1
        assert data["by_zone"][0]["zone"] == "llm"

    def test_admin_endpoints_require_admin(self, authenticated_client):
        """Non-admin user gets 403 on admin endpoints."""
        resp = authenticated_client.get("/api/v2/admin/feedback")
        assert resp.status_code == 403

        resp = authenticated_client.get("/api/v2/admin/feedback/stats")
        assert resp.status_code == 403
