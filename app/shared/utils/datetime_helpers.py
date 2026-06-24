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

    Args:
        expires_at: Optional expiration datetime

    Returns:
        True if expired, False otherwise
    """
    if expires_at is None:
        return False

    # Handle both timezone-aware and naive datetimes
    now = utcnow()
    if expires_at.tzinfo is None:
        # expires_at is naive, compare with naive datetime
        now = now.replace(tzinfo=None)

    return expires_at < now
