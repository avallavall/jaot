"""Regression tests for APIKeyService commit-inside-service contract (DEPLOY-06).

Prior behaviour: create_api_key flush()+refresh() without commit(); revoke_key
mutated is_active=False without commit(). Scripts that opened and closed a
session without explicit commit silently lost their changes. D-09 requires
the service to commit internally.

This test isolates its own Session (not the pytest fixture) so the internal
commit does not leak into other tests. Teardown deletes the rows explicitly.

The sessions come from ``db_engine``, not from the module-level ``SessionLocal``.
Two reasons, both bit us: ``db_engine`` is what applies the migrations, so
depending on it is what guarantees the schema exists — without it this file
passed only when the random test order happened to run something else first, and
errored with ``relation "organizations" does not exist`` when it went first. And
a module-level ``SessionLocal`` keeps the production factory whatever the harness
swaps in, so it wrote to whichever database ``DATABASE_URL`` named.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import APIKey, Organization, User
from app.services.auth import APIKeyService
from app.services.auth.password_service import PasswordService
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


@pytest.fixture
def new_session(db_engine):
    """A plain Session on the test engine — no SAVEPOINT, like a real script."""
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
def seeded_user_and_org(new_session):
    """Seed a user+org in its OWN session, commit, and teardown explicitly.

    We cannot reuse the pytest `db_session` SAVEPOINT fixture because the
    service itself now commits internally — the SAVEPOINT would be promoted
    and the rollback contract would break.
    """
    session = new_session()
    org_id = generate_id("org_")
    user_id = generate_id("usr_")
    org = Organization(id=org_id, name=f"deploy-06-test-{org_id}", is_active=True)
    user = User(
        id=user_id,
        email=f"{user_id}@deploy-06-test.local",
        name="deploy-06",
        organization_id=org_id,
        role="admin",
        is_active=True,
        password_hash=PasswordService.hash_password("AdminPass123!"),
        email_verified=True,
    )
    session.add_all([org, user])
    session.commit()
    try:
        yield session, user, org
    finally:
        # Cleanup in a fresh session to be robust to outer session state.
        cleanup = new_session()
        try:
            cleanup.query(APIKey).filter(APIKey.user_id == user_id).delete()
            cleanup.query(User).filter(User.id == user_id).delete()
            cleanup.query(Organization).filter(Organization.id == org_id).delete()
            cleanup.commit()
        finally:
            cleanup.close()
        session.close()


@pytest.mark.integration
def test_create_api_key_persists_across_session_close(seeded_user_and_org, new_session):
    session, user, org = seeded_user_and_org
    api_key, plaintext = APIKeyService.create_api_key(
        db=session,
        user_id=user.id,
        organization_id=org.id,
        name="DEPLOY-06 regression",
        prefix="ok_live_",
        expires_at=utcnow() + timedelta(minutes=10),
    )
    key_id = api_key.id
    session.close()

    # Fresh session — must see the row.
    check = new_session()
    try:
        row = check.query(APIKey).filter(APIKey.id == key_id).first()
        assert row is not None, "create_api_key must persist row without external commit"
        assert row.is_active is True
        assert plaintext.startswith("ok_live_")
    finally:
        check.close()


@pytest.mark.integration
def test_revoke_key_persists_across_session_close(seeded_user_and_org, new_session):
    session, user, org = seeded_user_and_org
    api_key, _ = APIKeyService.create_api_key(
        db=session,
        user_id=user.id,
        organization_id=org.id,
        name="DEPLOY-06 revoke regression",
        prefix="ok_live_",
        expires_at=utcnow() + timedelta(minutes=10),
    )
    key_id = api_key.id
    assert APIKeyService.revoke_key(session, key_id) is True
    session.close()

    check = new_session()
    try:
        row = check.query(APIKey).filter(APIKey.id == key_id).first()
        assert row is not None
        assert row.is_active is False, (
            "revoke_key must persist is_active=False without external commit"
        )
    finally:
        check.close()
