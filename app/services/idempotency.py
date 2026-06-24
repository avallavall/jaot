"""Idempotency execution ID derivation.

Extracted from app/api/v2/solve.py (Phase 12.5, D-01).

The derived execution_id is a financial-safety invariant: it gates whether a
retried solve request re-charges credits.  Two different orgs reusing the same
client-side Idempotency-Key cannot collide because the org_id is embedded in
the hash input.
"""

from __future__ import annotations

import hashlib


def idempotency_execution_id(idempotency_key: str, org_id: str, body_canonical: str) -> str:
    """Derive a stable execution_id from Idempotency-Key + org + body.

    Binds three inputs so the cache only hits on an actual retry of
    the same request (same org, same key, same body):

    1. ``org_id`` — two different orgs using the same client-side key
       cannot collide.
    2. ``idempotency_key`` — the header value the client sent.
    3. ``body_canonical`` — the canonical JSON serialization of the
       problem payload. If the client re-sends the same key with a
       different body (e.g. after fixing a constraint), the derived id
       is different and the retry executes fresh instead of returning
       the wrong cached result.

    Output: 24 chars of hex after the ``exe_ik_`` prefix.
    """
    digest = hashlib.sha256(f"{org_id}:{idempotency_key}:{body_canonical}".encode()).hexdigest()
    return f"exe_ik_{digest[:24]}"
