"""Password hashing service using argon2id (OWASP recommended)."""

import argon2
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# OWASP recommended: argon2id with time_cost=2, memory=19456 KiB, parallelism=1
_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=argon2.Type.ID,
)

# Pre-computed dummy hash for timing-safe comparison when user not found.
# This prevents timing attacks that could reveal whether an email exists.
DUMMY_HASH = _hasher.hash("__dummy_password_for_timing_safety__")


class PasswordService:
    """Argon2id password hashing and verification."""

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using argon2id.

        Args:
            password: Plain text password.

        Returns:
            Argon2id hash string starting with ``$argon2id$``.
        """
        return _hasher.hash(password)

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify a password against an argon2id hash.

        Uses timing-safe comparison internally (argon2-cffi).

        Args:
            password: Plain text password to verify.
            password_hash: Argon2id hash to verify against.

        Returns:
            True if password matches, False otherwise.
        """
        try:
            return _hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False

    @staticmethod
    def needs_rehash(password_hash: str) -> bool:
        """Check if a hash needs to be re-hashed with updated parameters.

        Args:
            password_hash: Existing argon2id hash.

        Returns:
            True if the hash should be regenerated.
        """
        return _hasher.check_needs_rehash(password_hash)
