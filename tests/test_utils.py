"""Tests for utility helper functions."""

from datetime import datetime, timedelta

from app.shared.utils.datetime_helpers import is_expired, utcnow
from app.shared.utils.id_generator import generate_api_key, generate_id, hash_api_key


def test_generate_id_default_length():
    """Test ID generation with default length."""
    id1 = generate_id("test_")
    id2 = generate_id("test_")

    assert id1.startswith("test_")
    assert id2.startswith("test_")
    assert id1 != id2  # Should be unique
    assert len(id1) == len("test_") + 16  # 8 bytes = 16 hex chars


def test_generate_id_custom_length():
    """Test ID generation with custom length."""
    id1 = generate_id("prefix_", length=4)
    assert len(id1) == len("prefix_") + 8  # 4 bytes = 8 hex chars


def test_generate_api_key():
    """Test API key generation."""
    key1, hash1 = generate_api_key("ok_test_")
    key2, hash2 = generate_api_key("ok_test_")

    assert key1.startswith("ok_test_")
    assert key2.startswith("ok_test_")
    assert key1 != key2
    assert hash1 != hash2
    assert len(key1) == len("ok_test_") + 64  # 32 bytes = 64 hex chars


def test_hash_api_key():
    """Test API key hashing."""
    key = "ok_test_123456"
    hash1 = hash_api_key(key)
    hash2 = hash_api_key(key)

    assert hash1 == hash2  # Same key = same hash
    assert len(hash1) == 64  # SHA-256 = 64 hex chars

    # Different key = different hash
    hash3 = hash_api_key("ok_test_different")
    assert hash1 != hash3


def test_utcnow_returns_datetime():
    """Test utcnow returns current datetime."""
    now = utcnow()
    assert isinstance(now, datetime)
    assert now.year >= 2024


def test_is_expired_none():
    """Test is_expired with None."""
    assert is_expired(None) is False


def test_is_expired_future_date():
    """Test is_expired with future date."""
    future = utcnow() + timedelta(days=1)
    assert is_expired(future) is False


def test_is_expired_past_date():
    """Test is_expired with past date."""
    past = utcnow() - timedelta(days=1)
    assert is_expired(past) is True


def test_is_expired_exact_now():
    """Test is_expired with current time."""
    # This is a bit tricky due to timing, but should be False
    now = utcnow()
    # Add small buffer to avoid race condition
    assert is_expired(now + timedelta(seconds=1)) is False
