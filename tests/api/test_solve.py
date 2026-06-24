"""
Tests for Universal Solve API endpoint.

These tests verify the solve functionality:
- Solving optimization problems
- Credit calculation
- Template-based solving
- Error handling
"""

from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    Variable,
    VariableType,
)


class TestCreditCalculation:
    """Tests for credit calculation logic."""

    def test_calculate_credits_simple_problem(self):
        """Test credit calculation for a simple problem."""
        from app.api.v2.solve import calculate_credits

        problem = OptimizationProblem(
            name="simple",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + y"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS),
                Variable(name="y", type=VariableType.CONTINUOUS),
            ],
            constraints=[
                Constraint(expression="x + y <= 10"),
            ],
        )

        credits = calculate_credits(problem)
        # Formula: base(1) + 2 vars * 0.1 + 0 mip + 1 cons * 0.05 + 0 time = 1.25 -> round -> 1
        assert credits == 1

    def test_calculate_credits_integer_variables(self):
        """Test credit calculation with integer variables."""
        from app.api.v2.solve import calculate_credits

        problem = OptimizationProblem(
            name="integer_problem",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + y"),
            variables=[
                Variable(name="x", type=VariableType.INTEGER),
                Variable(name="y", type=VariableType.INTEGER),
            ],
            constraints=[
                Constraint(expression="x + y <= 10"),
            ],
        )

        credits = calculate_credits(problem)
        # Formula: base(1) + 2 vars * 0.1 + sqrt(2) * 2.0 + 1 cons * 0.05 + 0 time
        #        = 1 + 0.2 + 2.828 + 0.05 = 4.078 -> round -> 4
        assert credits == 4

    def test_calculate_credits_complex_problem(self):
        """Test credit calculation for complex problem."""
        from app.api.v2.solve import calculate_credits

        problem = OptimizationProblem(
            name="complex",
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="sum"),
            variables=[Variable(name=f"x{i}", type=VariableType.BINARY) for i in range(10)],
            constraints=[Constraint(expression=f"x{i} <= 1") for i in range(10)],
            options=SolverOptions(time_limit_seconds=120),  # Long time limit
        )

        credits = calculate_credits(problem)
        # Formula: base(1) + 10 vars * 0.1 + sqrt(10) * 2.0 + 10 cons * 0.05 + ceil(60/60)
        #        = 1 + 1.0 + 6.324 + 0.5 + 1 = 9.824 -> round -> 10
        assert credits == 10

    def test_calculate_credits_minimum_is_one(self):
        """Test that minimum credits is always 1."""
        from app.api.v2.solve import calculate_credits

        problem = OptimizationProblem(
            name="minimal",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
            variables=[Variable(name="x", type=VariableType.CONTINUOUS)],
            constraints=[],
        )

        credits = calculate_credits(problem)
        assert credits >= 1


class TestSolveEndpoint:
    """Tests for POST /api/v2/solve endpoint."""

    def test_solve_requires_auth(self, client):
        """Test that solve requires authentication."""
        response = client.post(
            "/api/v2/solve",
            json={
                "name": "test",
                "objective": {"sense": "maximize", "expression": "x"},
                "variables": [{"name": "x", "type": "continuous"}],
                "constraints": [],
            },
        )
        assert response.status_code == 401

    def test_solve_insufficient_credits(self, authenticated_client, db_session, test_organization):
        """Test solve fails with insufficient credits."""
        test_organization.credits_balance = 0
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/solve",
            json={
                "name": "test",
                "objective": {"sense": "maximize", "expression": "x"},
                "variables": [{"name": "x", "type": "continuous"}],
                "constraints": [],
            },
        )

        # The contract is 402 Payment Required with INSUFFICIENT_CREDITS body.
        assert response.status_code == 402
        payload = response.json()
        detail = payload.get("detail", payload)
        # _pre_pay_credits raises HTTPException with detail={"error": "insufficient_credits", ...}
        assert detail.get("error") == "insufficient_credits"

    def test_solve_invalid_problem(self, authenticated_client, db_session, test_organization):
        """Test solve with invalid problem definition."""
        test_organization.credits_balance = 100
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/solve",
            json={
                "name": "invalid",
                # Missing required fields
            },
        )

        assert response.status_code == 422  # Validation error

    def test_solve_deducts_credits(self, authenticated_client, db_session, test_organization):
        """Test that solving deducts exactly calculate_credits(problem) credits."""
        from app.api.v2.solve import calculate_credits

        initial_balance = 100
        test_organization.credits_balance = initial_balance
        db_session.commit()

        problem_json = {
            "name": "credit_test",
            "objective": {"sense": "maximize", "expression": "x"},
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
            "constraints": [],
        }

        response = authenticated_client.post("/api/v2/solve", json=problem_json)
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:300]}"
        )

        expected_cost = calculate_credits(OptimizationProblem.model_validate(problem_json))
        db_session.refresh(test_organization)
        assert test_organization.credits_balance == initial_balance - expected_cost


class TestSolveConcurrency:
    """Concurrency and idempotency contracts for POST /api/v2/solve."""

    def test_concurrent_solve_no_double_spend(self, db_engine, db_session):
        """Two concurrent solve pre-payments against a tight balance must not double-spend.

        Scenario: credits_balance = exactly one pre_pay cost. Two threads fire
        a pre-pay at the same time. ``CreditsService.deduct_credits`` uses
        ``SELECT ... FOR UPDATE`` on the organization row, so exactly ONE
        thread must succeed and the other must raise
        InsufficientCreditsError. Final balance = 0, no overdraft.
        """
        import queue
        import threading

        from sqlalchemy.orm import sessionmaker

        from app.models import Organization
        from app.services.credits_service import CreditsService, InsufficientCreditsError
        from app.shared.utils.id_generator import generate_id

        Session = sessionmaker(bind=db_engine)

        # Create the org in its own session so the test's db_session does not
        # hold any lingering transaction on the row.
        setup_session = Session()
        try:
            org_id = generate_id("org_")
            org = Organization(
                id=org_id,
                name="Concurrent Solve Org",
                credits_balance=5,  # exactly one solve
                is_active=True,
            )
            setup_session.add(org)
            setup_session.commit()
        finally:
            setup_session.close()

        barrier = threading.Barrier(2)
        results: queue.Queue = queue.Queue()

        def _worker(thread_idx: int) -> None:
            session = Session()
            try:
                barrier.wait(timeout=10)
            except Exception as exc:
                results.put(("barrier_fail", thread_idx, str(exc)))
                session.close()
                return
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=5,
                    description=f"Concurrent pre-pay {thread_idx}",
                    reference_type="solve",
                    reference_id=generate_id("exe_"),
                )
                session.commit()
                results.put(("ok", thread_idx))
            except InsufficientCreditsError:
                session.rollback()
                results.put(("insufficient", thread_idx))
            except Exception as exc:  # pragma: no cover — unexpected
                session.rollback()
                results.put(("error", thread_idx, str(exc)))
            finally:
                session.close()

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        outcomes = []
        while not results.empty():
            outcomes.append(results.get())

        assert len(outcomes) == 2, f"Both threads must report; got: {outcomes}"
        tags = sorted(o[0] for o in outcomes)
        assert tags == ["insufficient", "ok"], f"Unexpected outcomes: {outcomes}"

        # Fresh read: exactly one successful deduction, balance now 0.
        fresh = Session()
        try:
            updated = fresh.query(Organization).filter_by(id=org_id).first()
            assert updated is not None, "Organization must still exist"
            assert updated.credits_balance == 0, f"Expected 0, got {updated.credits_balance}"
        finally:
            fresh.close()

    def test_solve_idempotency_key(self, authenticated_client, db_session, test_organization):
        """Retrying with the same Idempotency-Key charges once and returns the cached result.

        Contract: when the same key is sent twice, the second call must NOT
        deduct credits, must NOT create a second ModelExecution row, and must
        return the first execution's id.
        """
        from app.api.v2.solve import calculate_credits
        from app.models import ModelExecution, Organization
        from app.shared.core.rate_limiter import _memory_store
        from app.shared.utils.id_generator import generate_id

        _memory_store.clear()

        initial_balance = 100
        test_organization.credits_balance = initial_balance
        db_session.commit()

        problem_json = {
            "name": "idempotent_solve",
            "objective": {"sense": "maximize", "expression": "x"},
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 7}],
            "constraints": [],
        }
        expected_cost = calculate_credits(OptimizationProblem.model_validate(problem_json))

        idempotency_key = f"ik_{generate_id('test_')}"
        headers = {"Idempotency-Key": idempotency_key, "X-Forwarded-For": "10.99.99.2"}

        resp1 = authenticated_client.post("/api/v2/solve", json=problem_json, headers=headers)
        assert resp1.status_code == 200
        data1 = resp1.json()
        execution_id_1 = data1["execution_id"]

        # Second call with the SAME key — must not deduct again.
        resp2 = authenticated_client.post("/api/v2/solve", json=problem_json, headers=headers)
        assert resp2.status_code == 200
        data2 = resp2.json()

        # Both responses reference the same execution row.
        assert data2["execution_id"] == execution_id_1

        # Exactly one deduction.
        db_session.expire_all()
        updated = db_session.get(Organization, test_organization.id)
        assert updated.credits_balance == initial_balance - expected_cost

        # Exactly one ModelExecution row persisted for this key.
        rows = (
            db_session.query(ModelExecution)
            .filter(
                ModelExecution.id == execution_id_1,
                ModelExecution.organization_id == test_organization.id,
            )
            .all()
        )
        assert len(rows) == 1

    def test_solve_idempotency_key_rejects_body_mismatch(
        self, authenticated_client, db_session, test_organization
    ):
        """Same Idempotency-Key with DIFFERENT body must not return the cached result.

        Contract: the execution_id is derived from (org_id, key, body_hash).
        Reusing the key with a different problem payload yields a fresh
        execution, so the client never receives a cached response that
        doesn't match the request it just sent. Both requests are charged
        because they ARE different solves.
        """
        from app.api.v2.solve import calculate_credits
        from app.models import ModelExecution, Organization
        from app.shared.core.rate_limiter import _memory_store
        from app.shared.utils.id_generator import generate_id

        _memory_store.clear()

        initial_balance = 200
        test_organization.credits_balance = initial_balance
        db_session.commit()

        problem_a = {
            "name": "body_a",
            "objective": {"sense": "maximize", "expression": "x"},
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 7}],
            "constraints": [],
        }
        problem_b = {
            "name": "body_b",
            "objective": {"sense": "maximize", "expression": "x"},
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 13}],
            "constraints": [],
        }
        cost_a = calculate_credits(OptimizationProblem.model_validate(problem_a))
        cost_b = calculate_credits(OptimizationProblem.model_validate(problem_b))

        idempotency_key = f"ik_{generate_id('test_')}"
        headers = {"Idempotency-Key": idempotency_key, "X-Forwarded-For": "10.99.99.3"}

        resp_a = authenticated_client.post("/api/v2/solve", json=problem_a, headers=headers)
        assert resp_a.status_code == 200
        exe_id_a = resp_a.json()["execution_id"]

        # Same key, DIFFERENT body — must produce a fresh execution, not cache hit.
        resp_b = authenticated_client.post("/api/v2/solve", json=problem_b, headers=headers)
        assert resp_b.status_code == 200
        exe_id_b = resp_b.json()["execution_id"]

        assert exe_id_a != exe_id_b, (
            "Body-mismatched retry returned the cached execution_id — "
            "idempotency key must bind to request body hash."
        )

        # Both solves were charged (they're genuinely different problems).
        db_session.expire_all()
        updated = db_session.get(Organization, test_organization.id)
        assert updated.credits_balance == initial_balance - cost_a - cost_b

        # Two distinct ModelExecution rows.
        rows = (
            db_session.query(ModelExecution)
            .filter(
                ModelExecution.id.in_([exe_id_a, exe_id_b]),
                ModelExecution.organization_id == test_organization.id,
            )
            .all()
        )
        assert len(rows) == 2
