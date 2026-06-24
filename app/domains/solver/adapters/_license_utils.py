"""Pure utilities for parsing Hexaly platform-license metadata.

Phase 7.4 / D-10 / HEX-08: extracted from the deleted ``app/services/license_crypto.py``.
``HexalyAdapter`` (this package) and ``app/tasks/hexaly_platform_license_expiry.py``
(Celery beat sweep) are the only callers.

This module is intentionally crypto-free — Fernet encryption was BYOL-specific
and is removed in Plan 09. The ``.lic`` file is read as plaintext bytes from
the volume mount (per D-01) and parsed with regex for the human-readable
``EXPIRES=`` line.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

# Regex patterns used to scrape the ``expires_at`` hint from a .lic plaintext
# blob. Hexaly license files are opaque but frequently ship with a
# human-readable ``EXPIRES=YYYY-MM-DD`` or ``VALID_UNTIL=...`` line; when
# absent we fall back to any ``Expires / Expiration ...`` phrase. No match =>
# ``expires_at`` stays NULL and the system treats the license as "no known
# expiry" (SDK runtime errors still surface).
_EXPIRES_PATTERNS: list[re.Pattern[bytes]] = [
    re.compile(rb"^EXPIRES?\s*[=:]\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE | re.IGNORECASE),
    re.compile(rb"^VALID_UNTIL\s*[=:]\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE | re.IGNORECASE),
    re.compile(rb"Expir(?:es|ation)[^\d]*(\d{4}-\d{2}-\d{2})", re.IGNORECASE),
]


def fingerprint(plaintext: bytes) -> str:
    """Return the first 8 hex chars of sha256(plaintext).

    Used for UI display + audit logs + Prometheus gauge labels — safe to show
    without leaking the license itself.
    """
    return hashlib.sha256(plaintext).hexdigest()[:8]


def extract_expires_at(plaintext: bytes) -> datetime | None:
    """Best-effort regex scan for an ``expires_at`` hint in a .lic blob.

    Tries (in order) ``EXPIRES=``, ``VALID_UNTIL=``, ``Expires / Expiration
    ...``. Returns a timezone-aware UTC datetime at 00:00 on the detected
    day, or ``None`` when no pattern matches.
    """
    for pattern in _EXPIRES_PATTERNS:
        match = pattern.search(plaintext)
        if match:
            return datetime.strptime(match.group(1).decode(), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
    return None


__all__ = ["extract_expires_at", "fingerprint"]
