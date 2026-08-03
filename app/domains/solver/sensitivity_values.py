"""A solver's sentinel values must never be published as prices.

SCIP answers ``SCIP_INVALID`` (1e99) through ``getDualSolVal`` when a row has no
dual to report, and the sentinel rides the same ``double`` a real dual does.
Measured 2026-08-03, driving the adapter with two rows sharing one name (the
solve itself is correct — SCIP applies both): the surviving reference answered a
shadow price of ``-1e+99``, and the derivation then priced the variable's
reduced cost at ``2e+99``. Production served both as if a user could act on
them (QA 2026-08-02).

The guard is a threshold, not an equality against 1e99: SCIP states infinity as
1e20, HiGHS as 1e30, and no meaningful price reaches either. Anything at or
beyond the smallest of the family — or non-finite — is a sentinel.
"""

from __future__ import annotations

import math

# SCIP's own infinity, the smallest sentinel magnitude among the solvers served.
_SENTINEL_THRESHOLD = 1e20


def publishable_value(value: float | None) -> float | None:
    """``value`` if it is a number a user could act on, else ``None``."""
    if value is None:
        return None
    if not math.isfinite(value) or abs(value) >= _SENTINEL_THRESHOLD:
        return None
    return value
