"""Tests for community integration endpoints: DiscourseConnect SSO and community status."""

import base64
import hashlib
import hmac
from urllib.parse import parse_qs, urlparse

from app.models.platform_setting import PlatformSetting


def _set_pss(db, key, value):
    """Helper to set a platform setting in the test DB."""
    row = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
    if row:
        row.value = str(value)
    else:
        db.add(PlatformSetting(key=key, value=str(value), updated_by="test"))
    db.flush()


class TestDiscourseSso:
    """GET /api/v2/community/discourse-sso tests."""

    SSO_SECRET = "test-sso-secret"
    DISCOURSE_URL = "https://forum.example.com"

    def _build_sso_payload(self, nonce="random_nonce_123", return_url=None):
        """Build a valid DiscourseConnect SSO payload and signature."""
        parts = f"nonce={nonce}"
        if return_url:
            parts += f"&return_sso_url={return_url}"

        b64 = base64.b64encode(parts.encode()).decode()
        sig = hmac.new(self.SSO_SECRET.encode(), b64.encode(), hashlib.sha256).hexdigest()
        return b64, sig

    def test_sso_redirect_success(self, authenticated_client, test_user, db_session):
        """Valid SSO request returns 302 redirect to Discourse with signed payload."""
        _set_pss(db_session, "DISCOURSE_SSO_SECRET", self.SSO_SECRET)
        _set_pss(db_session, "DISCOURSE_URL", self.DISCOURSE_URL)

        b64, sig = self._build_sso_payload(return_url=f"{self.DISCOURSE_URL}/session/sso_login")

        resp = authenticated_client.get(
            f"/api/v2/community/discourse-sso?sso={b64}&sig={sig}",
            follow_redirects=False,
        )

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith(f"{self.DISCOURSE_URL}/session/sso_login?sso=")

    def test_sso_not_configured(self, authenticated_client, db_session):
        """Returns 503 when DISCOURSE_SSO_SECRET is empty."""
        _set_pss(db_session, "DISCOURSE_SSO_SECRET", "")

        b64 = base64.b64encode(b"nonce=abc").decode()
        resp = authenticated_client.get(
            f"/api/v2/community/discourse-sso?sso={b64}&sig=fakesig",
        )
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]

    def test_sso_invalid_signature(self, authenticated_client, db_session):
        """Returns 400 when the HMAC signature does not match."""
        _set_pss(db_session, "DISCOURSE_SSO_SECRET", self.SSO_SECRET)
        _set_pss(db_session, "DISCOURSE_URL", self.DISCOURSE_URL)

        b64 = base64.b64encode(b"nonce=abc").decode()
        wrong_sig = "0" * 64

        resp = authenticated_client.get(
            f"/api/v2/community/discourse-sso?sso={b64}&sig={wrong_sig}",
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid SSO signature"

    def test_sso_missing_params(self, authenticated_client):
        """Missing sso or sig query params returns 422."""
        # Missing both
        resp = authenticated_client.get("/api/v2/community/discourse-sso")
        assert resp.status_code == 422

        # Missing sig
        b64 = base64.b64encode(b"nonce=abc").decode()
        resp = authenticated_client.get(
            f"/api/v2/community/discourse-sso?sso={b64}",
        )
        assert resp.status_code == 422

        # Missing sso
        resp = authenticated_client.get(
            "/api/v2/community/discourse-sso?sig=abc",
        )
        assert resp.status_code == 422

    def test_sso_payload_contains_user_data(self, authenticated_client, test_user, db_session):
        """Redirect payload contains correct nonce, email, external_id, name, username."""
        _set_pss(db_session, "DISCOURSE_SSO_SECRET", self.SSO_SECRET)
        _set_pss(db_session, "DISCOURSE_URL", self.DISCOURSE_URL)

        nonce = "unique_nonce_456"
        b64, sig = self._build_sso_payload(
            nonce=nonce,
            return_url=f"{self.DISCOURSE_URL}/session/sso_login",
        )

        resp = authenticated_client.get(
            f"/api/v2/community/discourse-sso?sso={b64}&sig={sig}",
            follow_redirects=False,
        )

        assert resp.status_code == 302
        location = resp.headers["location"]
        parsed = urlparse(location)
        qs = parse_qs(parsed.query)

        # Decode the response SSO payload
        response_b64 = qs["sso"][0]
        response_decoded = base64.b64decode(response_b64).decode()
        response_params = parse_qs(response_decoded)

        assert response_params["nonce"][0] == nonce
        assert response_params["email"][0] == test_user.email
        assert response_params["external_id"][0] == test_user.id
        assert response_params["name"][0] == test_user.name
        assert response_params["suppress_welcome_message"][0] == "true"

        # Verify the response signature
        response_sig = qs["sig"][0]
        expected_sig = hmac.new(
            self.SSO_SECRET.encode(), response_b64.encode(), hashlib.sha256
        ).hexdigest()
        assert hmac.compare_digest(response_sig, expected_sig)

    def test_sso_username_from_email(self, authenticated_client, test_user, db_session):
        """Username is derived from the email local part (before @)."""
        _set_pss(db_session, "DISCOURSE_SSO_SECRET", self.SSO_SECRET)
        _set_pss(db_session, "DISCOURSE_URL", self.DISCOURSE_URL)

        b64, sig = self._build_sso_payload()

        resp = authenticated_client.get(
            f"/api/v2/community/discourse-sso?sso={b64}&sig={sig}",
            follow_redirects=False,
        )

        assert resp.status_code == 302
        location = resp.headers["location"]
        parsed = urlparse(location)
        qs = parse_qs(parsed.query)

        response_b64 = qs["sso"][0]
        response_decoded = base64.b64decode(response_b64).decode()
        response_params = parse_qs(response_decoded)

        expected_username = test_user.email.split("@")[0]
        assert response_params["username"][0] == expected_username

    def test_sso_default_return_url(self, authenticated_client, test_user, db_session):
        """When no return_sso_url in payload, uses DISCOURSE_URL + /session/sso_login."""
        _set_pss(db_session, "DISCOURSE_SSO_SECRET", self.SSO_SECRET)
        _set_pss(db_session, "DISCOURSE_URL", self.DISCOURSE_URL)

        # Build payload WITHOUT return_sso_url
        b64, sig = self._build_sso_payload(nonce="nonce_no_return")

        resp = authenticated_client.get(
            f"/api/v2/community/discourse-sso?sso={b64}&sig={sig}",
            follow_redirects=False,
        )

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith(f"{self.DISCOURSE_URL}/session/sso_login?sso=")


class TestCommunityStatus:
    """GET /api/v2/community/status tests."""

    def test_status_discourse_enabled(self, client, db_session):
        """Discourse configured returns correct flags and URL."""
        _set_pss(db_session, "DISCOURSE_SSO_SECRET", "secret")
        _set_pss(db_session, "DISCOURSE_URL", "https://forum.jaot.io")

        resp = client.get("/api/v2/community/status")
        assert resp.status_code == 200

        data = resp.json()
        assert data["discourse_enabled"] is True
        assert data["discourse_url"] == "https://forum.jaot.io"

    def test_status_none_enabled(self, client, db_session):
        """No secrets configured -- discourse disabled, url null."""
        _set_pss(db_session, "DISCOURSE_SSO_SECRET", "")
        _set_pss(db_session, "DISCOURSE_URL", "")

        resp = client.get("/api/v2/community/status")
        assert resp.status_code == 200

        data = resp.json()
        assert data["discourse_enabled"] is False
        assert data["discourse_url"] is None

    def test_status_discourse_url_missing(self, client, db_session):
        """Discourse SSO secret set but URL empty -- discourse_enabled is False."""
        _set_pss(db_session, "DISCOURSE_SSO_SECRET", "secret")
        _set_pss(db_session, "DISCOURSE_URL", "")

        resp = client.get("/api/v2/community/status")
        assert resp.status_code == 200

        data = resp.json()
        assert data["discourse_enabled"] is False
        assert data["discourse_url"] is None

    def test_status_is_public(self, client):
        """Community status endpoint is accessible without authentication."""
        resp = client.get("/api/v2/community/status")
        assert resp.status_code == 200
