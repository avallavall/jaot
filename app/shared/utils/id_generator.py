"""ID generation utilities."""

import hashlib
import secrets


def generate_id(prefix: str, length: int = 8) -> str:
    """Generate unique ID with prefix.

    Args:
        prefix: Prefix for the ID (e.g., "user_", "org_")
        length: Length of random part in bytes (default 8 = 16 hex chars)

    Returns:
        ID string like "user_a1b2c3d4e5f6"
    """
    return f"{prefix}{secrets.token_hex(length)}"


def generate_api_key(prefix: str = "ok_live_") -> tuple[str, str]:
    """Generate API key and its hash.

    Args:
        prefix: Key prefix (e.g., "ok_live_" or "ok_test_")

    Returns:
        Tuple of (full_key, key_hash)
    """
    # Generate 32 random bytes (64 hex chars)
    random_part = secrets.token_hex(32)
    full_key = f"{prefix}{random_part}"

    key_hash = hashlib.sha256(full_key.encode()).hexdigest()

    return full_key, key_hash


def hash_api_key(key: str) -> str:
    """Hash an API key.

    Args:
        key: Full API key

    Returns:
        SHA-256 hash of the key
    """
    return hashlib.sha256(key.encode()).hexdigest()
