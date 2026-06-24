"""Tests for API Key Service."""

import queue
import threading
from datetime import timedelta

from sqlalchemy.orm import sessionmaker

from app.services.auth.api_key_service import APIKeyService
from app.shared.utils.datetime_helpers import utcnow


def test_generate_key():
    """Test API key generation."""
    key, key_hash = APIKeyService.generate_key("ok_test_")

    assert key.startswith("ok_test_")
    assert len(key) == len("ok_test_") + 64  # 32 bytes = 64 hex chars
    assert len(key_hash) == 64  # SHA-256 = 64 hex chars

    # Second generation should be different
    key2, hash2 = APIKeyService.generate_key("ok_test_")
    assert key != key2
    assert key_hash != hash2


def test_hash_key_consistency():
    """Test key hashing is consistent."""
    key = "ok_test_123456"
    hash1 = APIKeyService.hash_key(key)
    hash2 = APIKeyService.hash_key(key)

    assert hash1 == hash2
    assert len(hash1) == 64


def test_create_api_key(db_session, test_user, test_organization):
    """Test creating an API key."""
    api_key, plaintext = APIKeyService.create_api_key(
        db=db_session,
        user_id=test_user.id,
        organization_id=test_organization.id,
        name="Test Key",
        prefix="ok_test_",
    )

    assert api_key.id.startswith("key_")
    assert api_key.user_id == test_user.id
    assert api_key.organization_id == test_organization.id
    assert api_key.name == "Test Key"
    assert api_key.is_active is True
    assert plaintext.startswith("ok_test_")


def test_create_api_key_with_expiration(db_session, test_user, test_organization):
    """Test creating API key with expiration and that verify_key treats it as expired.

    After creating the key, we fast-forward the expiration into the past and
    assert that verify_key returns None — i.e. the expiration is not just
    stored, it is actually honored by the verification path.
    """
    expires = (utcnow() + timedelta(days=30)).replace(tzinfo=None)

    api_key, plaintext = APIKeyService.create_api_key(
        db=db_session,
        user_id=test_user.id,
        organization_id=test_organization.id,
        expires_at=expires,
    )

    assert api_key.expires_at == expires

    # Now fast-forward expires_at into the past and verify the key is rejected.
    api_key.expires_at = (utcnow() - timedelta(days=1)).replace(tzinfo=None)
    db_session.commit()
    assert APIKeyService.verify_key(db_session, plaintext) is None


def test_verify_valid_key(db_session, test_api_key, test_user, test_organization):
    """Test verifying a valid API key."""
    result = APIKeyService.verify_key(db_session, test_api_key.plaintext)

    assert result is not None
    api_key, user, org = result

    assert api_key.id == test_api_key.id
    assert user.id == test_user.id
    assert org.id == test_organization.id


def test_verify_invalid_key(db_session):
    """Test verifying an invalid API key."""
    result = APIKeyService.verify_key(db_session, "ok_test_invalid_key")
    assert result is None


def test_verify_expired_key(db_session, expired_api_key):
    """Test verifying an expired API key."""
    result = APIKeyService.verify_key(db_session, expired_api_key.plaintext)
    assert result is None


def test_verify_inactive_key(db_session, test_api_key):
    """Test verifying an inactive API key."""
    # Deactivate the key
    test_api_key.is_active = False
    db_session.commit()

    result = APIKeyService.verify_key(db_session, test_api_key.plaintext)
    assert result is None


def test_verify_key_with_inactive_user(db_session, test_api_key, test_user):
    """Test verifying key when user is inactive."""
    test_user.is_active = False
    db_session.commit()

    result = APIKeyService.verify_key(db_session, test_api_key.plaintext)
    assert result is None


def test_verify_key_with_inactive_org(db_session, test_api_key, test_organization):
    """Test verifying key when organization is inactive."""
    test_organization.is_active = False
    db_session.commit()

    result = APIKeyService.verify_key(db_session, test_api_key.plaintext)
    assert result is None


def test_verify_key_updates_last_used(db_session, test_api_key):
    """Test that verifying updates last_used_at timestamp."""
    assert test_api_key.last_used_at is None

    APIKeyService.verify_key(db_session, test_api_key.plaintext)
    db_session.refresh(test_api_key)

    assert test_api_key.last_used_at is not None


def test_revoke_key(db_session, test_api_key):
    """Test revoking an API key."""
    assert test_api_key.is_active is True

    result = APIKeyService.revoke_key(db_session, test_api_key.id)
    assert result is True

    # Service now commits internally (DEPLOY-06). Caller commit is a no-op
    # (idempotent) but kept here for explicitness in the test session context.
    db_session.commit()
    db_session.refresh(test_api_key)
    assert test_api_key.is_active is False


def test_revoke_nonexistent_key(db_session):
    """Test revoking a non-existent key."""
    result = APIKeyService.revoke_key(db_session, "key_nonexistent")
    assert result is False


def test_list_keys(db_session, test_user, test_organization):
    """Test listing API keys for a user."""
    # Create multiple keys
    key1, _ = APIKeyService.create_api_key(
        db_session, test_user.id, test_organization.id, name="Key 1"
    )
    key2, _ = APIKeyService.create_api_key(
        db_session, test_user.id, test_organization.id, name="Key 2"
    )

    keys = APIKeyService.list_keys(db_session, test_user.id)

    assert len(keys) == 2
    key_ids = [k.id for k in keys]
    assert key1.id in key_ids
    assert key2.id in key_ids


def test_list_keys_empty(db_session):
    """Test listing keys when user has none."""
    keys = APIKeyService.list_keys(db_session, "user_nonexistent")
    assert len(keys) == 0


def test_verify_key_unrecognized_prefix_rejected(db_session):
    """A key whose prefix is NEITHER the live nor the test prefix is rejected at
    the prefix gate (verify_key lines 112-114) before any hash lookup.

    Gap (mutmut-v24 §1): test_verify_invalid_key uses 'ok_test_invalid_key',
    which DOES start with the test prefix, so it exercises the not-found path,
    never the unrecognized-prefix branch. A garbage prefix must return None — a
    drop/flip of that guard would fall through to a (futile) hash lookup.
    """
    assert APIKeyService.verify_key(db_session, "xyz_not_a_jaot_key_123") is None


def test_list_keys_scoped_by_organization(
    db_session, test_user, test_organization, test_organization_2
):
    """list_keys(organization_id=X) returns ONLY the user's keys in org X.

    Pins the optional org filter (api_key_service.py:181-182): dropping it would
    leak a user's keys from other orgs into a tenant-scoped listing.
    """
    key_org1, _ = APIKeyService.create_api_key(
        db_session, test_user.id, test_organization.id, name="org1 key"
    )
    key_org2, _ = APIKeyService.create_api_key(
        db_session, test_user.id, test_organization_2.id, name="org2 key"
    )

    # Unscoped: both keys for the user.
    all_keys = APIKeyService.list_keys(db_session, test_user.id)
    assert {k.id for k in all_keys} == {key_org1.id, key_org2.id}

    # Scoped to org1: only org1's key (the org filter must exclude org2's).
    org1_keys = APIKeyService.list_keys(
        db_session, test_user.id, organization_id=test_organization.id
    )
    assert [k.id for k in org1_keys] == [key_org1.id], (
        f"org-scoped list_keys must return only org1's key, got {[k.id for k in org1_keys]}"
    )


def test_verify_test_key_rejected_in_production(db_session, test_api_key, monkeypatch):
    """A test-prefixed key (``ok_test_``) must be REJECTED when DEBUG is False.

    This is the production safety branch in ``verify_key`` (lines 116-119):

        if not settings.DEBUG and key.startswith(test_prefix):
            return None

    Mutmut 3.5.0 cannot enumerate the @staticmethod auth mutants (settrace
    stats-mapping limitation — AUDIT §16.6), so this gap is closed by manual
    test-mapping. Without this assertion the production guard could be inverted
    (``not settings.DEBUG`` → ``settings.DEBUG``; ``and`` → ``or``;
    ``startswith(test_prefix)`` dropped/flipped) and a test key would be
    accepted in production — a silent authn weakness. ``verify_key`` imports
    ``settings`` lazily inside the function, so patching ``settings.DEBUG``
    here is seen by the call.
    """
    from app.config import settings

    # The fixture key uses the ``ok_test_`` (test) prefix.
    assert test_api_key.plaintext.startswith("ok_test_")

    # Positive branch: in DEBUG (default) the test key verifies OK.
    monkeypatch.setattr(settings, "DEBUG", True)
    assert APIKeyService.verify_key(db_session, test_api_key.plaintext) is not None

    # Negative branch: with DEBUG False, the same test key is rejected.
    monkeypatch.setattr(settings, "DEBUG", False)
    assert APIKeyService.verify_key(db_session, test_api_key.plaintext) is None


def test_verify_live_key_accepted_in_production(
    db_session, test_user, test_organization, monkeypatch
):
    """A live-prefixed key (``ok_live_``) must STILL verify when DEBUG is False.

    Companion to ``test_verify_test_key_rejected_in_production``: proves the
    production guard is scoped to the *test* prefix only (it rejects test keys,
    not all keys). This kills a mutant that broadens the rejection to live keys
    (e.g. ``startswith(test_prefix)`` → ``startswith(live_prefix)``) which would
    lock every real customer out of production.
    """
    from app.config import settings

    api_key, plaintext = APIKeyService.create_api_key(
        db=db_session,
        user_id=test_user.id,
        organization_id=test_organization.id,
        name="Live Key",
        prefix="ok_live_",
    )
    db_session.commit()
    assert plaintext.startswith("ok_live_")

    monkeypatch.setattr(settings, "DEBUG", False)
    result = APIKeyService.verify_key(db_session, plaintext)
    assert result is not None
    verified_key, user, org = result
    assert verified_key.id == api_key.id
    assert user.id == test_user.id
    assert org.id == test_organization.id


def test_verify_key_with_missing_user_row(db_session, test_api_key, monkeypatch):
    """verify_key returns None when the api_key row resolves but the associated
    USER row is missing (``get_user_or_none`` → None).

    Gap (mutmut-v24 §1, line 137): the existing suite covers an *inactive* user
    (``test_verify_key_with_inactive_user``, line 139 branch) but never the
    *missing* user branch at line 136 (``if not user or not organization``).
    The FK ``api_keys.user_id -> users.id`` (no ON DELETE) makes a hard-deleted
    user impossible to produce via the DB, so the line is a defensive guard
    against an inconsistency/race. We pin it honestly by forcing the service's
    own user lookup to miss; dropping the ``not user`` guard would dereference a
    None user downstream (``user.is_active``) and crash the auth path instead of
    cleanly rejecting.
    """
    from app.services.auth import api_key_service as svc

    # The org still resolves; only the user lookup misses.
    monkeypatch.setattr(svc, "get_user_or_none", lambda db, user_id: None)
    assert APIKeyService.verify_key(db_session, test_api_key.plaintext) is None


def test_verify_key_with_missing_org_row(db_session, test_api_key, monkeypatch):
    """verify_key returns None when the api_key row resolves but the associated
    ORGANIZATION row is missing (``get_organization_or_none`` → None).

    Companion to ``test_verify_key_with_missing_user_row``: pins the second
    operand of the line-136 guard. The user resolves but the org lookup misses,
    so the ``not organization`` half must reject. Killing the ``or`` (e.g.
    ``and``) would let a key with a vanished org through.
    """
    from app.services.auth import api_key_service as svc

    monkeypatch.setattr(svc, "get_organization_or_none", lambda db, organization_id: None)
    assert APIKeyService.verify_key(db_session, test_api_key.plaintext) is None


def test_concurrent_verify_key_no_race(db_session, db_engine, test_api_key, test_user):
    """Two concurrent verify_key calls must both succeed and leave
    api_keys.last_used_at in a consistent (non-NULL, monotonically set) state.

    Regression guard against a read/modify/write race on last_used_at that
    would surface as one of the concurrent calls returning None (key rejected)
    or last_used_at being left as NULL after both calls completed.
    """
    assert test_api_key.last_used_at is None

    results: queue.Queue = queue.Queue()
    barrier = threading.Barrier(5, timeout=15)
    Session = sessionmaker(bind=db_engine, expire_on_commit=False)
    plaintext = test_api_key.plaintext

    def worker(thread_id: int) -> None:
        session = Session()
        try:
            barrier.wait()
            result = APIKeyService.verify_key(session, plaintext)
            session.commit()
            if result is None:
                results.put(("rejected", thread_id))
            else:
                api_key, user, _org = result
                results.put(("ok", thread_id, api_key.id, user.id, api_key.last_used_at))
        except Exception as exc:
            session.rollback()
            results.put(("error", thread_id, str(exc)))
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=(i,), name=f"apikey-verify-{i}") for i in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    for t in threads:
        assert not t.is_alive(), f"thread {t.name} did not finish"

    outcomes = []
    while not results.empty():
        outcomes.append(results.get())

    oks = [o for o in outcomes if o[0] == "ok"]
    rejects = [o for o in outcomes if o[0] == "rejected"]
    errors = [o for o in outcomes if o[0] == "error"]

    # All 5 must succeed — no concurrent rejection, no exception
    assert len(errors) == 0, f"errors in concurrent verify_key: {errors}"
    assert len(rejects) == 0, f"concurrent verify_key should never reject: {rejects}"
    assert len(oks) == 5, f"expected 5 successes, got {len(oks)}"

    # Each success returned the same api_key.id and user.id
    assert all(o[2] == test_api_key.id for o in oks)
    assert all(o[3] == test_user.id for o in oks)

    # last_used_at must be set (non-NULL) after the calls
    db_session.refresh(test_api_key)
    assert test_api_key.last_used_at is not None
