"""Tests for guidance endpoints (skill level and wizard state)."""


class TestGetGuidance:
    """GET /api/v2/guidance tests."""

    def test_get_guidance_defaults(self, authenticated_client):
        """New user returns beginner skill level and default wizard state."""
        resp = authenticated_client.get("/api/v2/guidance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["skill_level"] == "beginner"
        assert data["wizard_step"] == 0
        assert data["wizard_dismissed"] is False
        assert data["wizard_completed"] is False

    def test_get_guidance_unauthenticated(self, client):
        """Unauthenticated request returns 401."""
        resp = client.get("/api/v2/guidance")
        assert resp.status_code == 401


class TestUpdateGuidance:
    """PATCH /api/v2/guidance tests."""

    def test_update_skill_level(self, authenticated_client):
        """PATCH with skill_level='expert' persists and returns correctly."""
        resp = authenticated_client.patch("/api/v2/guidance", json={"skill_level": "expert"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["skill_level"] == "expert"
        # Defaults preserved
        assert data["wizard_step"] == 0
        assert data["wizard_dismissed"] is False

        # Verify persistence via GET
        resp2 = authenticated_client.get("/api/v2/guidance")
        assert resp2.json()["skill_level"] == "expert"

    def test_update_wizard_step(self, authenticated_client):
        """PATCH with wizard_step=2 persists in guidance_state JSON."""
        resp = authenticated_client.patch("/api/v2/guidance", json={"wizard_step": 2})
        assert resp.status_code == 200
        assert resp.json()["wizard_step"] == 2

        # Verify persistence
        resp2 = authenticated_client.get("/api/v2/guidance")
        assert resp2.json()["wizard_step"] == 2

    def test_update_wizard_dismissed(self, authenticated_client):
        """PATCH with wizard_dismissed=true persists."""
        resp = authenticated_client.patch("/api/v2/guidance", json={"wizard_dismissed": True})
        assert resp.status_code == 200
        assert resp.json()["wizard_dismissed"] is True

    def test_update_wizard_completed(self, authenticated_client):
        """PATCH with wizard_completed=true persists."""
        resp = authenticated_client.patch("/api/v2/guidance", json={"wizard_completed": True})
        assert resp.status_code == 200
        assert resp.json()["wizard_completed"] is True

    def test_partial_update_preserves_other_fields(self, authenticated_client):
        """Updating skill_level doesn't reset wizard_step."""
        # First set wizard_step
        authenticated_client.patch("/api/v2/guidance", json={"wizard_step": 3})

        # Then update skill_level only
        resp = authenticated_client.patch("/api/v2/guidance", json={"skill_level": "intermediate"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["skill_level"] == "intermediate"
        assert data["wizard_step"] == 3  # preserved

    def test_invalid_skill_level(self, authenticated_client):
        """PATCH with invalid skill_level returns 422."""
        resp = authenticated_client.patch("/api/v2/guidance", json={"skill_level": "invalid"})
        assert resp.status_code == 422

    def test_wizard_step_validation_too_high(self, authenticated_client):
        """PATCH with wizard_step=6 returns 422."""
        resp = authenticated_client.patch("/api/v2/guidance", json={"wizard_step": 6})
        assert resp.status_code == 422

    def test_wizard_step_validation_negative(self, authenticated_client):
        """PATCH with wizard_step=-1 returns 422."""
        resp = authenticated_client.patch("/api/v2/guidance", json={"wizard_step": -1})
        assert resp.status_code == 422


class TestMeIncludesGuidance:
    """GET /api/v2/auth/me guidance fields tests."""

    def test_me_includes_guidance_fields(self, authenticated_client):
        """GET /auth/me returns skill_level and guidance_state."""
        resp = authenticated_client.get("/api/v2/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert "skill_level" in data
        assert data["skill_level"] == "beginner"
        assert "guidance_state" in data

    def test_me_reflects_guidance_updates(self, authenticated_client):
        """After updating guidance, /auth/me reflects changes."""
        authenticated_client.patch(
            "/api/v2/guidance", json={"skill_level": "expert", "wizard_step": 4}
        )

        resp = authenticated_client.get("/api/v2/auth/me")
        data = resp.json()
        assert data["skill_level"] == "expert"
        assert data["guidance_state"]["wizard_step"] == 4
