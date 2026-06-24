"""Prepaid-credits carrier helpers for async solve payloads.

Phase 7 / simplify-2 / Q-28. Async solve / model-execution dispatch
sites embed a pre-paid credit amount inside the Celery task kwargs
dict (``problem_data`` or ``input_data``) under the private
``_prepaid_credits`` key so the worker can refund idempotently on
failure without re-reading the DB.

The key is internal — no API contract, no client-visible surface. These
helpers wrap the dict-access so every site uses the same idiom and the
key string lives in exactly one place (grepability, safe rename).

Usage::

    problem_data["_prepaid_credits"] = credits_needed   # BEFORE
    set_prepaid_credits(problem_data, credits_needed)   # AFTER

    prepaid = problem_data.get("_prepaid_credits", 0)   # BEFORE
    prepaid = get_prepaid_credits(problem_data)         # AFTER

    problem_data["_prepaid_credits"] = 0                 # BEFORE (cancel marker)
    clear_prepaid_credits(problem_data)                  # AFTER
"""

from __future__ import annotations

from typing import Any

# Private key — solver-domain-internal carrier for pre-paid credit counts
# across the dispatch -> worker boundary. Grepping for ``_PREPAID_CREDITS_KEY``
# finds every use site; grepping for the raw string finds helper + tests
# only.
_PREPAID_CREDITS_KEY = "_prepaid_credits"


def get_prepaid_credits(payload: dict[str, Any] | None) -> int:
    """Return the prepaid credit count carried on ``payload``.

    ``0`` when the key is missing, the payload is ``None``, or the stored
    value is not an int (defensive — the field is an internal contract,
    but legacy task retries might carry a missing marker).
    """
    if not payload:
        return 0
    value = payload.get(_PREPAID_CREDITS_KEY, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def set_prepaid_credits(payload: dict[str, Any], credits: int) -> None:
    """Stamp ``payload`` with the pre-paid credit count.

    Mutates the dict in place (consistent with existing callers that
    mutate ``problem_data`` before enqueuing).
    """
    payload[_PREPAID_CREDITS_KEY] = int(credits)


def clear_prepaid_credits(payload: dict[str, Any]) -> None:
    """Set the pre-paid credit count to ``0`` on ``payload``.

    Used by the cancel-endpoint flow (CR-01) so the worker's except
    branch treats the cancellation as "no refund owed" — the key is
    preserved (set to 0) rather than deleted so downstream consumers
    can still detect the explicit cancel marker.
    """
    payload[_PREPAID_CREDITS_KEY] = 0


__all__ = [
    "clear_prepaid_credits",
    "get_prepaid_credits",
    "set_prepaid_credits",
]
