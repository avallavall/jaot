"""# CONTRACT-TEST: a user cannot hold unlimited live API keys.

There was no cap. Driving the app as a plain member, 20 creations in a row all
returned 200 and the account ended up holding 24 keys, with nothing on the page
suggesting there was a number to stay under.

Every key is a standing credential that outlives a password change, so the
ceiling is on how many are LIVE at once: revoking one frees a slot, and an
expired one occupies none.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import APIKey, User
from app.models.platform_setting import PlatformSetting
from app.shared.utils.datetime_helpers import utcnow

pytestmark = pytest.mark.integration


def _set_limit(db: Session, value: int) -> None:
    row = (
        db.query(PlatformSetting)
        .filter(PlatformSetting.key == "AUTH_MAX_ACTIVE_API_KEYS_PER_USER")
        .first()
    )
    if row:
        row.value = str(value)
    else:
        db.add(
            PlatformSetting(
                key="AUTH_MAX_ACTIVE_API_KEYS_PER_USER",
                value=str(value),
                updated_by="test",
            )
        )
    db.commit()


def _create(client: TestClient, name: str):
    return client.post("/api/v2/keys/", json={"name": name})


def _live_keys(db: Session, user: User) -> list[APIKey]:
    return (
        db.query(APIKey)
        .filter(APIKey.user_id == user.id, APIKey.is_active == True)  # noqa: E712
        .all()
    )


class TestApiKeyLimit:
    def test_creation_is_refused_once_the_limit_is_reached(
        self, authenticated_client: TestClient, db_session: Session, test_user: User
    ):
        _set_limit(db_session, len(_live_keys(db_session, test_user)) + 2)

        assert _create(authenticated_client, "one").status_code == 200
        assert _create(authenticated_client, "two").status_code == 200
        refused = _create(authenticated_client, "three")

        assert refused.status_code == 409
        detail = refused.json()["detail"]
        # The number has to be in the message: a limit a user cannot see is one
        # they meet as an unexplained failure.
        assert "limit" in detail.lower()
        assert any(ch.isdigit() for ch in detail)

    def test_revoking_a_key_frees_a_slot(
        self, authenticated_client: TestClient, db_session: Session, test_user: User
    ):
        _set_limit(db_session, len(_live_keys(db_session, test_user)) + 1)

        created = _create(authenticated_client, "the only one")
        assert created.status_code == 200
        assert _create(authenticated_client, "one too many").status_code == 409

        revoke = authenticated_client.delete(f"/api/v2/keys/{created.json()['id']}")
        assert revoke.status_code == 200

        assert _create(authenticated_client, "after revoking").status_code == 200

    def test_an_expired_key_occupies_no_slot(
        self, authenticated_client: TestClient, db_session: Session, test_user: User
    ):
        """An expired key is spent. Counting it would lock a user out forever."""
        _set_limit(db_session, len(_live_keys(db_session, test_user)) + 1)

        created = _create(authenticated_client, "will expire")
        assert created.status_code == 200
        row = db_session.query(APIKey).filter(APIKey.id == created.json()["id"]).one()
        row.expires_at = utcnow() - timedelta(days=1)
        db_session.commit()

        assert _create(authenticated_client, "after the other expired").status_code == 200

    def test_a_limit_of_zero_turns_the_cap_off(
        self, authenticated_client: TestClient, db_session: Session
    ):
        """The documented escape hatch for an operator who wants no ceiling."""
        _set_limit(db_session, 0)

        for i in range(6):
            assert _create(authenticated_client, f"uncapped {i}").status_code == 200

    def test_the_cap_is_per_user_not_per_organization(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_user: User,
    ):
        """A colleague filling their own quota must not lock this user out.

        The keys belong to the user, and so does the ceiling.
        """
        limit = len(_live_keys(db_session, test_user)) + 1
        _set_limit(db_session, limit)

        colleague = User(
            id="usr_key_limit_colleague",
            email="colleague-keylimit@example.com",
            name="Colleague",
            organization_id=test_user.organization_id,
            is_active=True,
        )
        db_session.add(colleague)
        db_session.flush()
        for i in range(limit + 3):
            db_session.add(
                APIKey(
                    id=f"key_colleague_{i}",
                    user_id=colleague.id,
                    organization_id=test_user.organization_id,
                    key_hash=f"hash_colleague_{i}",
                    key_prefix=f"ok_live_c{i}",
                    name=f"colleague key {i}",
                    is_active=True,
                )
            )
        db_session.commit()

        assert _create(authenticated_client, "mine").status_code == 200
