"""Tests for database helper functions."""

from app.shared.utils.db_helpers import (
    get_api_key_by_hash,
    get_organization_or_none,
    get_user_or_none,
)


def test_get_organization_or_none_success(db_session, test_organization):
    """Test getting organization or None (success case)."""
    org = get_organization_or_none(db_session, test_organization.id)
    assert org is not None
    assert org.id == test_organization.id


def test_get_organization_or_none_returns_none(db_session):
    """Test getting organization or None (not found case)."""
    org = get_organization_or_none(db_session, "org_nonexistent")
    assert org is None


def test_get_user_or_none_success(db_session, test_user):
    """Test getting user or None (success case)."""
    user = get_user_or_none(db_session, test_user.id)
    assert user is not None
    assert user.id == test_user.id
    assert user.email == test_user.email


def test_get_user_or_none_returns_none(db_session):
    """Test getting user or None (not found case)."""
    user = get_user_or_none(db_session, "user_nonexistent")
    assert user is None


def test_get_api_key_by_hash_success(db_session, test_api_key):
    """Test getting API key by hash."""
    api_key = get_api_key_by_hash(db_session, test_api_key.key_hash)
    assert api_key is not None
    assert api_key.id == test_api_key.id


def test_get_api_key_by_hash_returns_none(db_session):
    """Test getting API key by hash (not found case)."""
    api_key = get_api_key_by_hash(db_session, "nonexistent_hash")
    assert api_key is None
