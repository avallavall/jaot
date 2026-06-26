"""Tests for the BYOK org Anthropic-key endpoints (app/api/v2/org_settings.py).

Owner-only writes, masked reads, encryption at rest. Auth + DB are real.
"""

from app.models import Organization
from app.services.llm import byok

URL = "/api/v2/organization/anthropic-key"
VALID_KEY = "sk-ant-api03-test-key-abcdefghij1234"


def _make_owner(db_session, org, user):
    org.owner_user_id = user.id
    db_session.commit()


class TestSetAnthropicKey:
    def test_owner_can_set_key_encrypted_at_rest(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _make_owner(db_session, test_organization, test_user)

        resp = authenticated_client.put(URL, json={"api_key": VALID_KEY})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["enabled"] is True
        assert body["hint"] == "sk-ant-…1234"

        # Stored encrypted — never the plaintext — but decrypts back to it.
        db_session.expire_all()
        org = db_session.query(Organization).filter(Organization.id == test_organization.id).first()
        assert org.anthropic_api_key_encrypted
        assert org.anthropic_api_key_encrypted != VALID_KEY
        assert byok.decrypt_api_key(org.anthropic_api_key_encrypted) == VALID_KEY

    def test_invalid_format_rejected(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _make_owner(db_session, test_organization, test_user)
        resp = authenticated_client.put(URL, json={"api_key": "totally-not-an-anthropic-key-123"})
        assert resp.status_code == 422

    def test_non_owner_forbidden(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        # owner_user_id left unset → the authenticated member is not the owner.
        resp = authenticated_client.put(URL, json={"api_key": VALID_KEY})
        assert resp.status_code == 403

    def test_requires_auth(self, client):
        resp = client.put(URL, json={"api_key": VALID_KEY})
        assert resp.status_code == 401


class TestGetAndClearAnthropicKey:
    def test_owner_sees_hint_after_setting(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _make_owner(db_session, test_organization, test_user)
        authenticated_client.put(URL, json={"api_key": VALID_KEY})

        resp = authenticated_client.get(URL)
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["hint"] == "sk-ant-…1234"

    def test_non_owner_member_sees_enabled_but_no_hint(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        # Set the key as owner first, then read as a non-owner member.
        _make_owner(db_session, test_organization, test_user)
        authenticated_client.put(URL, json={"api_key": VALID_KEY})
        # Drop ownership so the authenticated user is a plain member (None avoids
        # the owner FK; the point is simply that user.id != owner_user_id).
        test_organization.owner_user_id = None
        db_session.commit()

        resp = authenticated_client.get(URL)
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["hint"] is None  # members don't get the hint

    def test_owner_can_clear_key(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _make_owner(db_session, test_organization, test_user)
        authenticated_client.put(URL, json={"api_key": VALID_KEY})

        resp = authenticated_client.delete(URL)
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        db_session.expire_all()
        org = db_session.query(Organization).filter(Organization.id == test_organization.id).first()
        assert org.anthropic_api_key_encrypted is None
