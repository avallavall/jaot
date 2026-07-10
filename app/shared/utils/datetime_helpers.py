"""Datetime helper utilities."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Get current UTC time.

    Centralized for easy mocking in tests.
    Uses timezone-aware datetime as recommended by Python 3.12+.

    Returns:
        Current UTC datetime (timezone-aware)
    """
    return datetime.now(timezone.utc)


def is_expired(expires_at: datetime | None) -> bool:
    """Check if datetime is expired.

    DB columns are timestamptz (aware UTC) since the S6 migration; a naive
    value can only come from legacy external input and is treated as UTC.

    Args:
        expires_at: Optional expiration datetime

    Returns:
        True if expired, False otherwise
    """
    if expires_at is None:
        return False

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return expires_at < utcnow()
