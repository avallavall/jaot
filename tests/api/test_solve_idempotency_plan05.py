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
    functions"). A quadratic objective would take the failure+refund path,
    leaving no credit debit to assert the single-charge invariant against.
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


def test_solve_duplicate_idempotency_key_returns_same_execution(
    authenticated_client, test_organization, db_session
):
    """SC5 (non-financial, owner=PLAN_05): POST /api/v2/solve with duplicate
    Idempotency-Key returns the same execution_id AND charges credits once.

    Per 12.4-01-idempotency-coverage.md verdict FOUND-1:
    ``POST /api/v2/solve`` (app/api/v2/solve.py:289) is the only public
    Idempotency-Key-bearing endpoint in app/api/v2/. The dedup binds
    (org_id, Idempotency-Key, canonical_body) into a stable execution_id
    (app/api/v2/solve.py:283-286); replays return the cached
    ``ModelExecution`` row instead of re-solving and re-deducting credits.

    Pattern: PATTERNS Pattern 2 Variant B (sequential 2-call).

    Test invariants:
    1. Both responses MUST return 200 (idempotent dedup, not error).
    2. Both responses MUST share the same ``execution_id`` field.
    3. Both responses MUST share the same ``status`` and ``objective_value``
       (the second is a cache hit, not a re-solve).
    4. The org's ``credits_balance`` is debited exactly ONCE across the two
       calls (real-DB read-back). The synchronous solve pre-pays
       ``credits_needed`` (app/services/solve_orchestrator.py:221-232); the
       replay returns the persisted result WITHOUT reaching the orchestrator
       (app/api/v2/solve.py:322-338), so it must not debit a second time.
       A double-charge would leave the balance at ``starting - 2*credits_used``.
    """
    key = "sc5_solve_dup_001"
    body = _linear_problem_payload()
    headers = {"Idempotency-Key": key}

    # authenticated_client is bound to test_organization (org_test001); the
    # autouse get_db override makes the request share this db_session, so the
    # org row read-back below reflects the in-request credit debit.
    starting_balance = test_organization.credits_balance

    first = authenticated_client.post("/api/v2/solve", json=body, headers=headers)
    db_session.refresh(test_organization)
    balance_after_first = test_organization.credits_balance

    second = authenticated_client.post("/api/v2/solve", json=body, headers=headers)
    db_session.refresh(test_organization)
    balance_after_second = test_organization.credits_balance

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

    # SC5 financial invariant: a paid solve debits credits exactly ONCE.
    # Precondition -- the LP (minimize x s.t. x>=1) solves to OPTIMAL, so the
    # first call took the pre-pay path with no refund. objective_value is None
    # only on the failure/refund path, which would make the single-charge
    # arithmetic below moot, so assert success explicitly first.
    assert first_body.get("objective_value") is not None, (
        f"Expected a successful paid solve (non-None objective_value); got "
        f"status={first_body.get('status')} body={first_body}"
    )
    credits_used = first_body["credits_used"]
    assert credits_used >= 1, (
        f"calculate_credits returns max(1, ...), so a real solve must cost >=1 "
        f"credit for the once-vs-twice distinction to be meaningful; got {credits_used}."
    )
    # First call debited exactly credits_used from the real org row.
    assert balance_after_first == starting_balance - credits_used, (
        f"SC5 financial violation: first solve debited "
        f"{starting_balance - balance_after_first} credits, expected {credits_used} "
        f"(starting={starting_balance}, after_first={balance_after_first})."
    )
    # The replay (cache hit) must NOT debit again -- balance is unchanged.
    assert balance_after_second == balance_after_first, (
        f"SC5 financial violation: duplicate Idempotency-Key re-charged on replay. "
        f"after_first={balance_after_first} after_second={balance_after_second} "
        f"(expected unchanged). A second debit means the dedup guard failed."
    )
    # The replay reports the same accounting as the original (cache hit).
    assert second_body["credits_used"] == credits_used, (
        f"Replay credits_used drifted: first={credits_used} second={second_body['credits_used']}"
    )
    assert second_body["credits_remaining"] == first_body["credits_remaining"], (
        f"Replay credits_remaining drifted: first={first_body['credits_remaining']} "
        f"second={second_body['credits_remaining']}"
    )
