"""SC5 non-financial idempotency test for POST /api/v2/solve.

Phase 12.4 Plan 05 Task 4 Step 4b -- closes the FOUND-1 outcome of
12.4-01-idempotency-coverage.md: POST /api/v2/solve carries an
``Idempotency-Key`` header and is owned by Plan 05 (non-financial; the path
does not match the financial regex). One SC5 sequential-duplicate test
proves the dedup mechanism returns the same execution_id for two requests
with the same (Idempotency-Key, body) tuple.

Pattern adapted from PATTERNS Pattern 2 Variant B (sequential 2-call) and
tests/test_cancel_refund_idempotency.py:46 (CR-01) sequential variant.
"""

from __future__ import annotations


def _linear_problem_payload() -> dict:
    """Minimal LP payload that SCIP solves to OPTIMAL (x=1, objective=1).

    Linear (not quadratic): the default solver is SCIP, which rejects
    nonlinear objectives ("SCIP does not support nonlinear objective
    functions"). A quadratic objective would take the failure path,
    leaving no completed execution to assert the executed-once invariant
    against.
    """
    return {
        "name": "sc5_solve_idempotency_lp",
        "variables": [
            {"name": "x", "type": "continuous", "lower_bound": 0.0, "upper_bound": 10.0},
        ],
        "constraints": [{"name": "c1", "expression": "x >= 1"}],
        "objective": {"expression": "x", "sense": "minimize"},
        "options": {"time_limit_seconds": 10.0, "verbose": False},
    }


# CONTRACT-TEST: solve-idempotency-key-dedup
#   Duplicate Idempotency-Key on POST /solve returns the SAME execution_id and
#   leaves exactly ONE ModelExecution row — the replay attaches, never re-solves.
#   Removing this test removes the only executed-once regression guard.
def test_solve_duplicate_idempotency_key_returns_same_execution(
    authenticated_client, test_organization, db_session
):
    """SC5 (owner=PLAN_05): POST /api/v2/solve with duplicate
    Idempotency-Key returns the same execution_id and does not re-solve.

    Per 12.4-01-idempotency-coverage.md verdict FOUND-1:
    ``POST /api/v2/solve`` (app/api/v2/solve.py:289) is the only public
    Idempotency-Key-bearing endpoint in app/api/v2/. The dedup binds
    (org_id, Idempotency-Key, canonical_body) into a stable execution_id
    (app/api/v2/solve.py:283-286); replays return the cached
    ``ModelExecution`` row instead of re-solving.

    Pattern: PATTERNS Pattern 2 Variant B (sequential 2-call).

    Test invariants:
    1. Both responses MUST return 200 (idempotent dedup, not error).
    2. Both responses MUST share the same ``execution_id`` field.
    3. Both responses MUST share the same ``status`` and ``objective_value``
       (the second is a cache hit, not a re-solve).
    4. Exactly ONE ``ModelExecution`` row exists for the shared
       ``execution_id`` (real-DB read-back) -- the replay attaches to the
       original run instead of solving again (ADR-008: the credit ledger is
       gone; the single-row invariant is what executed-once means now).
    """
    key = "sc5_solve_dup_001"
    body = _linear_problem_payload()
    headers = {"Idempotency-Key": key}

    # authenticated_client is bound to test_organization (org_test001); the
    # autouse get_db override makes the request share this db_session, so the
    # single-row read-back below sees the rows written in-request.
    first = authenticated_client.post("/api/v2/solve", json=body, headers=headers)
    second = authenticated_client.post("/api/v2/solve", json=body, headers=headers)

    assert first.status_code == 200, (
        f"First solve call did not succeed: {first.status_code} {first.text[:200]}"
    )
    assert second.status_code == 200, (
        f"Duplicate solve call did not return 200: {second.status_code} {second.text[:200]}"
    )

    first_body = first.json()
    second_body = second.json()

    # Both responses must carry the same execution_id (idempotent dedup).
    assert "execution_id" in first_body, f"First response missing execution_id: {first_body}"
    assert "execution_id" in second_body, f"Second response missing execution_id: {second_body}"
    assert first_body["execution_id"] == second_body["execution_id"], (
        f"SC5 violation: execution_id differs across duplicate Idempotency-Key calls. "
        f"first={first_body['execution_id']} second={second_body['execution_id']}"
    )

    # Cache-hit invariant: solver status and objective_value must match.
    assert first_body.get("status") == second_body.get("status"), (
        f"SC5 violation: status drifted across duplicate calls. "
        f"first={first_body.get('status')} second={second_body.get('status')}"
    )
    assert first_body.get("objective_value") == second_body.get("objective_value"), (
        f"SC5 violation: objective_value drifted across duplicate calls. "
        f"first={first_body.get('objective_value')} second={second_body.get('objective_value')}"
    )

    # SC5 executed-once invariant: exactly one ModelExecution row exists for
    # the shared execution_id -- the replay attached, it did not re-solve.
    from app.models import ModelExecution

    rows = (
        db_session.query(ModelExecution)
        .filter(ModelExecution.id == first_body["execution_id"])
        .count()
    )
    assert rows == 1, f"Expected exactly one ModelExecution row, got {rows}"
