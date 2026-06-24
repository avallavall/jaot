"""Tests for the public home announcement endpoint.

Covers the contract used by the public layout banner:
- GET /api/v2/home/announcement is reachable without authentication
- enabled=false (default) returns an empty banner payload
- enabled=true + empty text for the requested locale returns empty messages
- enabled=true + non-empty text returns the split messages (rotation via '|')
- Unknown locales gracefully fall back to English
- The rotation interval is echoed in the response
"""

from __future__ import annotations

import pytest

from app.services.platform_settings_service import PlatformSettingsService as PSS

PATH = "/api/v2/home/announcement"


@pytest.fixture
def reset_announcement(db_session):
    """Restore the announcement settings to defaults after each test."""
    yield
    PSS.set(db_session, "HOME_ANNOUNCEMENT_ENABLED", "false")
    PSS.set(db_session, "HOME_ANNOUNCEMENT_TEXT_EN", "")
    PSS.set(db_session, "HOME_ANNOUNCEMENT_TEXT_ES", "")
    PSS.set(db_session, "HOME_ANNOUNCEMENT_TEXT_CA", "")
    PSS.set(db_session, "HOME_ANNOUNCEMENT_TEXT_FR", "")
    PSS.set(db_session, "HOME_ANNOUNCEMENT_TEXT_DE", "")
    PSS.set(db_session, "HOME_ANNOUNCEMENT_ROTATION_SECONDS", "5")
    db_session.commit()


class TestHomeAnnouncementEndpoint:
    """GET /api/v2/home/announcement contract."""

    def test_public_no_auth_required(self, client):
        """Endpoint responds without an Authorization header."""
        response = client.get(PATH)
        assert response.status_code == 200

    def test_disabled_by_default(self, client):
        """With no settings touched, the banner reports as disabled."""
        response = client.get(PATH)
        body = response.json()
        assert body["enabled"] is False
        assert body["messages"] == []
        assert isinstance(body["rotation_seconds"], int)

    def test_enabled_but_empty_text_returns_empty(self, client, db_session, reset_announcement):
        """Enabled flag without locale text → empty messages and enabled=False."""
        PSS.set(db_session, "HOME_ANNOUNCEMENT_ENABLED", "true")
        PSS.set(db_session, "HOME_ANNOUNCEMENT_TEXT_EN", "")
        db_session.commit()

        body = client.get(f"{PATH}?locale=en").json()
        assert body["enabled"] is False
        assert body["messages"] == []

    def test_single_message(self, client, db_session, reset_announcement):
        """A single message is returned as a one-element list."""
        PSS.set(db_session, "HOME_ANNOUNCEMENT_ENABLED", "true")
        PSS.set(db_session, "HOME_ANNOUNCEMENT_TEXT_EN", "Welcome!")
        db_session.commit()

        body = client.get(f"{PATH}?locale=en").json()
        assert body["enabled"] is True
        assert body["messages"] == ["Welcome!"]

    def test_multi_message_split_on_pipe(self, client, db_session, reset_announcement):
        """Pipe-separated text splits into multiple messages with trim."""
        PSS.set(db_session, "HOME_ANNOUNCEMENT_ENABLED", "true")
        PSS.set(
            db_session,
            "HOME_ANNOUNCEMENT_TEXT_EN",
            "Promo 20% | Maintenance Saturday |  Empty fragments dropped  |",
        )
        db_session.commit()

        body = client.get(f"{PATH}?locale=en").json()
        assert body["enabled"] is True
        assert body["messages"] == [
            "Promo 20%",
            "Maintenance Saturday",
            "Empty fragments dropped",
        ]

    def test_per_locale_isolation(self, client, db_session, reset_announcement):
        """Each locale reads its own text key."""
        PSS.set(db_session, "HOME_ANNOUNCEMENT_ENABLED", "true")
        PSS.set(db_session, "HOME_ANNOUNCEMENT_TEXT_ES", "Hola mundo")
        PSS.set(db_session, "HOME_ANNOUNCEMENT_TEXT_EN", "Hello world")
        db_session.commit()

        es = client.get(f"{PATH}?locale=es").json()
        en = client.get(f"{PATH}?locale=en").json()
        assert es["messages"] == ["Hola mundo"]
        assert en["messages"] == ["Hello world"]

    def test_unknown_locale_falls_back_to_en(self, client, db_session, reset_announcement):
        """Unknown locale codes are silently coerced to 'en'."""
        PSS.set(db_session, "HOME_ANNOUNCEMENT_ENABLED", "true")
        PSS.set(db_session, "HOME_ANNOUNCEMENT_TEXT_EN", "fallback")
        db_session.commit()

        body = client.get(f"{PATH}?locale=zz").json()
        assert body["messages"] == ["fallback"]

    def test_rotation_seconds_echoed(self, client, db_session, reset_announcement):
        """rotation_seconds reflects the admin-configured value."""
        PSS.set(db_session, "HOME_ANNOUNCEMENT_ROTATION_SECONDS", "12")
        db_session.commit()

        body = client.get(PATH).json()
        assert body["rotation_seconds"] == 12
