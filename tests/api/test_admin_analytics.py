"""Tests for admin feature analytics endpoint.

Verifies GET /api/v2/admin/marketplace/feature-analytics returns complete
analytics overview with KPI, time series, breakdown, domain summary, funnel,
and recent events.
"""

from datetime import timedelta

from app.models.analytics_event import AnalyticsEvent
from app.models.organization import Organization
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


class TestAdminFeatureAnalytics:
    """Test admin feature analytics endpoint."""

    ENDPOINT = "/api/v2/admin/marketplace/feature-analytics"

    def test_get_overview_returns_200(self, admin_client) -> None:
        """GET /feature-analytics returns 200 with all expected keys."""
        response = admin_client.get(self.ENDPOINT)
        assert response.status_code == 200
        data = response.json()

        expected_keys = {
            "kpi",
            "time_series",
            "event_breakdown",
            "domain_summary",
            "funnel",
            "grouped_time_series",
            "country_distribution",
        }
        assert set(data.keys()) == expected_keys

    def test_get_overview_default_period(self, admin_client) -> None:
        """Default period is 7d."""
        response = admin_client.get(self.ENDPOINT)
        assert response.status_code == 200
        data = response.json()

        # KPI section includes the period
        assert data["kpi"]["period"] == "7d"

    def test_get_overview_all_periods(self, admin_client) -> None:
        """Each valid period (1h, 12h, today, 7d, 30d, 90d, all) returns 200."""
        valid_periods = ["1h", "12h", "today", "7d", "30d", "90d", "all"]
        for period in valid_periods:
            response = admin_client.get(f"{self.ENDPOINT}?period={period}")
            assert response.status_code == 200, f"Period '{period}' returned {response.status_code}"
            data = response.json()
            assert data["kpi"]["period"] == period

    def test_get_overview_invalid_period(self, admin_client) -> None:
        """Invalid period returns 422."""
        response = admin_client.get(f"{self.ENDPOINT}?period=5d")
        assert response.status_code == 422

    def test_get_overview_requires_admin(self, authenticated_client) -> None:
        """Non-admin user receives 403."""
        response = authenticated_client.get(self.ENDPOINT)
        assert response.status_code == 403

    def test_overview_kpi_structure(self, admin_client) -> None:
        """KPI section has total_events, active_users, events_today, top_event_type."""
        response = admin_client.get(self.ENDPOINT)
        assert response.status_code == 200
        kpi = response.json()["kpi"]

        assert "total_events" in kpi
        assert "active_users" in kpi
        assert "events_today" in kpi
        assert "top_event_type" in kpi
        assert "top_event_count" in kpi
        assert "period" in kpi

        # Types
        assert isinstance(kpi["total_events"], int)
        assert isinstance(kpi["active_users"], int)
        assert isinstance(kpi["events_today"], int)

    def test_overview_funnel_structure(self, admin_client) -> None:
        """Funnel section has steps array."""
        response = admin_client.get(self.ENDPOINT)
        assert response.status_code == 200
        funnel = response.json()["funnel"]

        assert "steps" in funnel
        assert isinstance(funnel["steps"], list)
        assert len(funnel["steps"]) == 4  # signup -> create -> solve -> purchase

        for step in funnel["steps"]:
            assert "name" in step
            assert "value" in step
            assert "fill" in step

    def test_overview_with_events(self, admin_client, db_session) -> None:
        """Create AnalyticsEvent records, then verify counts > 0."""
        now = utcnow().replace(tzinfo=None)
        events = [
            AnalyticsEvent(
                user_id="user_admin001",
                org_id="org_test001",
                event_type="user.signup",
                country_code="US",
                created_at=now - timedelta(hours=1),
            ),
            AnalyticsEvent(
                user_id="user_admin001",
                org_id="org_test001",
                event_type="solver.solve",
                event_metadata={"credits_used": 5},
                created_at=now - timedelta(minutes=30),
            ),
            AnalyticsEvent(
                user_id="user_other",
                org_id="org_test001",
                event_type="user.signup",
                country_code="DE",
                created_at=now - timedelta(hours=2),
            ),
        ]
        db_session.add_all(events)
        db_session.commit()

        response = admin_client.get(f"{self.ENDPOINT}?period=7d")
        assert response.status_code == 200
        data = response.json()

        # KPI should reflect the events
        assert data["kpi"]["total_events"] == 3
        assert data["kpi"]["active_users"] == 2

        # Event breakdown should have entries
        assert len(data["event_breakdown"]) > 0
        breakdown_types = {e["event_type"] for e in data["event_breakdown"]}
        assert "user.signup" in breakdown_types
        assert "solver.solve" in breakdown_types

        # Funnel should have user.signup step with value 2 (unique users)
        signup_step = next(s for s in data["funnel"]["steps"] if s["name"] == "user.signup")
        assert signup_step["value"] == 2

        # Time series should have data points
        assert len(data["time_series"]["data"]) > 0


class TestAdminAnalyticsCrossOrgIsolation:
    """Verify admin analytics endpoints' tenant isolation contract."""

    ENDPOINT = "/api/v2/admin/marketplace/feature-analytics"

    def test_admin_overview_is_intentionally_global(
        self, admin_client, db_session, test_organization
    ) -> None:
        """The admin overview endpoint is GLOBAL by design (platform-wide).

        It aggregates events across all orgs because admins need a single
        platform health dashboard. This test pins that contract: an admin
        querying with no org filter sees events from BOTH orgs in the
        breakdown. Without this guard, a future "tenant safety" change
        that accidentally scopes admin overview to one org would silently
        break the platform dashboard.
        """
        # Plant a second org with its own events
        other_org = Organization(
            id=generate_id("org_"),
            name="Cross-Org Sibling",
            credits_balance=100,
            is_active=True,
        )
        db_session.add(other_org)
        db_session.flush()

        now = utcnow().replace(tzinfo=None)
        events = [
            AnalyticsEvent(
                id=generate_id("ae_"),
                user_id="usr_iso_a",
                org_id=test_organization.id,
                event_type="user.signup",
                created_at=now - timedelta(hours=1),
            ),
            AnalyticsEvent(
                id=generate_id("ae_"),
                user_id="usr_iso_b",
                org_id=other_org.id,
                event_type="user.signup",
                created_at=now - timedelta(hours=2),
            ),
        ]
        db_session.add_all(events)
        db_session.commit()

        response = admin_client.get(f"{self.ENDPOINT}?period=7d")
        assert response.status_code == 200
        data = response.json()
        # Both orgs' events must contribute to the global total
        assert data["kpi"]["total_events"] >= 2
        assert data["kpi"]["active_users"] >= 2

    def test_admin_overview_blocks_non_admin(
        self, authenticated_client, db_session, test_organization
    ) -> None:
        """Non-admin users hitting the admin overview must receive 403.

        This is the enforcement point that prevents a regular org user
        from reading the platform-wide admin dashboard (the only place
        that legitimately crosses tenant lines).
        """
        # Even with planted events, the non-admin client must be 403
        ev = AnalyticsEvent(
            id=generate_id("ae_"),
            user_id="usr_iso_c",
            org_id=test_organization.id,
            event_type="user.signup",
            created_at=utcnow().replace(tzinfo=None),
        )
        db_session.add(ev)
        db_session.commit()

        response = authenticated_client.get(self.ENDPOINT)
        assert response.status_code == 403
