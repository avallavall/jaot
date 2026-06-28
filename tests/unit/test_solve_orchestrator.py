"""Tests for SolveOrchestrator credit-flow correctness and deduplication.

Covers:
- C1: Pool capacity check runs BEFORE credit deduction (no credits lost on 429)
- C2: ANY SolverStatus.ERROR triggers refund (not just validation errors)
- C3: solve_multi_objective refunds on solver error
- I1: _execute_with_credits helper deduplicates solve scaffolding
- I3: CREDITS_CONSUMED metric not incremented when refund is issued
- I4: PSS.get_int called once per public method (not once per PSS.get_int usage)
"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from app.schemas.optimization import (
    MultiObjectiveConfig,
    OptimizationProblem,
    OptimizationResult,
    SolverStatus,
)
from app.services.solve_orchestrator import (
    ORIGIN_MANUAL,
    ORIGIN_TEMPLATE,
    ExecutionSource,
    SolveOrchestrator,
)


def _make_request(debug: bool = False) -> MagicMock:
    """Return a minimal mock FastAPI Request."""
    req = MagicMock(spec=Request)
    req.headers = {"X-Jaot-Debug": "true"} if debug else {}
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    req.url = MagicMock()
    req.url.path = "/api/v2/solve"
    return req


def _make_org(credits: int = 100) -> MagicMock:
    """Return a mock Organization with a credits_balance."""
    org = MagicMock()
    org.id = "org_test001"
    org.credits_balance = credits
    org.plan = "free"
    return org


def _make_problem() -> MagicMock:
    """Return a minimal mock OptimizationProblem."""
    problem = MagicMock(spec=OptimizationProblem)
    problem.name = "test_problem"
    problem.variables = []
    return problem


def _make_result(status: SolverStatus = SolverStatus.OPTIMAL) -> MagicMock:
    """Return a mock OptimizationResult."""
    result = MagicMock(spec=OptimizationResult)
    result.status = status
    result.error_message = None
    result.credits_used = None
    result.credits_remaining = None
    result.sensitivity = None
    return result


def _make_pool(saturated: bool = False, pool_size: int = 4) -> ThreadPoolExecutor:
    """Return a real ThreadPoolExecutor.

    For saturated pools: mock _work_queue to return a large queue size.
    For normal pools: do NOT mock _work_queue (Python 3.14 breaks submit if mocked).
    """
    pool = ThreadPoolExecutor(max_workers=pool_size)
    if saturated:
        # Only mock _work_queue for the saturated case (pool check raises 429 before
        # run_in_executor is ever called, so the broken submit is not an issue).
        queue_mock = MagicMock()
        queue_mock.qsize.return_value = pool_size * 2
        pool._work_queue = queue_mock  # type: ignore[attr-defined]
    # For non-saturated pools: leave _work_queue real. getattr returns the real
    # SimpleQueue which reports qsize() == 0 when idle, so the capacity check passes.
    return pool


def _make_orchestrator(
    db: MagicMock | None = None,
    solver: MagicMock | None = None,
    pool: ThreadPoolExecutor | MagicMock | None = None,
) -> SolveOrchestrator:
    """Create SolveOrchestrator with safe mock defaults."""
    if db is None:
        db = MagicMock()
        refreshed_org = _make_org(credits=90)
        db.query.return_value.filter.return_value.first.return_value = refreshed_org
    if solver is None:
        solver = MagicMock()
        solver.solve.return_value = _make_result()
        solver.solve_multi_objective.return_value = []
    if pool is None:
        pool = _make_pool()
    return SolveOrchestrator(db=db, solver=solver, solver_pool=pool)


class TestC1PoolCheckBeforeCredits:
    """Credits must NOT be deducted when the pool is at capacity.

    All 3 public methods delegate to _execute_with_credits, which must call
    _check_pool_capacity before _pre_pay_credits (C1 fix).
    """

    async def test_solve_single_pool_429_no_credit_deduction(self):
        """solve_single: pool saturated → 429, credits_balance unchanged."""
        pool = _make_pool(saturated=True)
        orchestrator = _make_orchestrator(pool=pool)

        with patch.object(orchestrator, "_pre_pay_credits") as mock_prepay:
            with pytest.raises(HTTPException) as exc_info:
                await orchestrator.solve_single(
                    problem=_make_problem(),
                    org=_make_org(),
                    user=None,
                    request=_make_request(),
                    credits_needed=10,
                )
            assert exc_info.value.status_code == 429
            # Pre-pay must NOT have been called
            mock_prepay.assert_not_called()

    async def test_solve_multi_objective_pool_429_no_credit_deduction(self):
        """solve_multi_objective: pool saturated → 429, credits unchanged."""
        pool = _make_pool(saturated=True)
        orchestrator = _make_orchestrator(pool=pool)

        with patch.object(orchestrator, "_pre_pay_credits") as mock_prepay:
            with pytest.raises(HTTPException) as exc_info:
                config = MagicMock(spec=MultiObjectiveConfig)
                config.objectives = []
                config.mode = "weighted_sum"
                await orchestrator.solve_multi_objective(
                    problem=_make_problem(),
                    config=config,
                    org=_make_org(),
                    user=None,
                    request=_make_request(),
                    total_credits=10,
                )
            assert exc_info.value.status_code == 429
            mock_prepay.assert_not_called()

    async def test_solve_with_template_pool_429_no_credit_deduction(self):
        """solve_with_template: pool saturated → 429, credits unchanged."""
        pool = _make_pool(saturated=True)
        orchestrator = _make_orchestrator(pool=pool)

        with patch.object(orchestrator, "_pre_pay_credits") as mock_prepay:
            with pytest.raises(HTTPException) as exc_info:
                await orchestrator.solve_with_template(
                    problem=_make_problem(),
                    template_id="tpl_001",
                    org=_make_org(),
                    user=None,
                    request=_make_request(),
                    credits_needed=10,
                )
            assert exc_info.value.status_code == 429
            mock_prepay.assert_not_called()


class TestC2C3RefundOnAllErrors:
    """_execute_with_credits refunds on any SolverStatus.ERROR.

    These tests call _execute_with_credits directly (via an async wrapper) to
    avoid Windows-specific asyncio.run_in_executor() issues in CI while still
    confirming the core credit-flow contract. The public-method tests in C1
    confirm the methods route through _execute_with_credits.
    """

    async def _run_execute_with_result(self, result: MagicMock) -> MagicMock:
        """Run _execute_with_credits with a mocked solve_fn, return mock_refund."""
        orchestrator = _make_orchestrator()

        with patch.object(orchestrator, "_pre_pay_credits"):
            with patch.object(orchestrator, "_refund_credits") as mock_refund:
                with patch("app.services.solve_orchestrator.ACTIVE_SOLVES"):
                    with patch("app.services.solve_orchestrator.SOLVE_DURATION"):
                        with patch("app.services.solve_orchestrator.SOLVE_TOTAL"):
                            with patch("app.services.solve_orchestrator.CREDITS_CONSUMED"):
                                await orchestrator._execute_with_credits(
                                    solve_fn=lambda: result,
                                    credits_needed=10,
                                    org=_make_org(),
                                    workspace_id=None,
                                    execution_id="exe_test",
                                    request=_make_request(),
                                    generator_label="direct",
                                    timeout_seconds=30,
                                )
                return mock_refund

    async def _run_execute_with_exception(self, exc: Exception) -> MagicMock:
        """Run _execute_with_credits with a solve_fn that raises, return mock_refund."""
        orchestrator = _make_orchestrator()

        with patch.object(orchestrator, "_pre_pay_credits"):
            with patch.object(orchestrator, "_refund_credits") as mock_refund:
                with patch("app.services.solve_orchestrator.ACTIVE_SOLVES"):
                    with patch("app.services.solve_orchestrator.SOLVE_DURATION"):
                        with patch("app.services.solve_orchestrator.SOLVE_TOTAL"):
                            with patch("app.services.solve_orchestrator.CREDITS_CONSUMED"):
                                with pytest.raises(type(exc)):
                                    await orchestrator._execute_with_credits(
                                        solve_fn=lambda: (_ for _ in ()).throw(exc),
                                        credits_needed=10,
                                        org=_make_org(),
                                        workspace_id=None,
                                        execution_id="exe_test",
                                        request=_make_request(),
                                        generator_label="direct",
                                        timeout_seconds=30,
                                    )
                return mock_refund

    async def test_error_result_with_validation_message_refunds(self):
        """ERROR result with 'validation' message → refund triggered (C2)."""
        result = _make_result(status=SolverStatus.ERROR)
        result.error_message = "validation failed"
        mock_refund = await self._run_execute_with_result(result)
        mock_refund.assert_called_once()

    async def test_error_result_with_infeasible_message_refunds(self):
        """ERROR result with 'infeasible' message → refund triggered (C2)."""
        result = _make_result(status=SolverStatus.ERROR)
        result.error_message = "problem is infeasible"
        mock_refund = await self._run_execute_with_result(result)
        mock_refund.assert_called_once()

    async def test_error_result_with_no_message_refunds(self):
        """ERROR result with None message → refund triggered (C2)."""
        result = _make_result(status=SolverStatus.ERROR)
        result.error_message = None
        mock_refund = await self._run_execute_with_result(result)
        mock_refund.assert_called_once()

    async def test_error_result_with_random_message_refunds(self):
        """ERROR result with arbitrary message → refund triggered (C2)."""
        result = _make_result(status=SolverStatus.ERROR)
        result.error_message = "unexpected solver crash"
        mock_refund = await self._run_execute_with_result(result)
        mock_refund.assert_called_once()

    async def test_optimal_result_does_not_refund(self):
        """OPTIMAL result → no refund."""
        result = _make_result(status=SolverStatus.OPTIMAL)
        mock_refund = await self._run_execute_with_result(result)
        mock_refund.assert_not_called()

    async def test_solver_exception_refunds(self):
        """Any exception from solve_fn triggers refund (C3 path)."""
        mock_refund = await self._run_execute_with_exception(RuntimeError("crash"))
        mock_refund.assert_called_once()


class TestI1ExecuteWithCreditsHelper:
    """_execute_with_credits must exist and be called by all 3 public methods."""

    def test_helper_method_exists(self):
        """SolveOrchestrator has _execute_with_credits method."""
        orch = _make_orchestrator()
        assert hasattr(orch, "_execute_with_credits"), (
            "_execute_with_credits not found on SolveOrchestrator"
        )
        assert callable(orch._execute_with_credits)

    async def test_solve_single_calls_helper(self):
        """solve_single delegates to _execute_with_credits."""
        orch = _make_orchestrator()
        result = _make_result(SolverStatus.OPTIMAL)
        result.sensitivity = None

        async def _fake_execute(*args, **kwargs):
            return result

        with patch.object(orch, "_execute_with_credits", side_effect=_fake_execute) as mock_helper:
            with patch("app.services.solve_orchestrator.PSS") as mock_pss:
                mock_pss.get_int.return_value = 30
                mock_pss.get_plan_config_dynamic.return_value = {"allowed_features": []}
                await orch.solve_single(
                    problem=_make_problem(),
                    org=_make_org(),
                    user=None,
                    request=_make_request(),
                    credits_needed=5,
                )
        mock_helper.assert_called_once()

    async def test_solve_multi_objective_calls_helper(self):
        """solve_multi_objective delegates to _execute_with_credits."""
        orch = _make_orchestrator()

        async def _fake_execute(*args, **kwargs):
            return []

        with patch.object(orch, "_execute_with_credits", side_effect=_fake_execute) as mock_helper:
            with patch("app.services.solve_orchestrator.PSS") as mock_pss:
                mock_pss.get_int.return_value = 30
                config = MagicMock(spec=MultiObjectiveConfig)
                config.objectives = []
                config.mode = "weighted_sum"
                await orch.solve_multi_objective(
                    problem=_make_problem(),
                    config=config,
                    org=_make_org(),
                    user=None,
                    request=_make_request(),
                    total_credits=5,
                )
        mock_helper.assert_called_once()

    async def test_solve_with_template_calls_helper(self):
        """solve_with_template delegates to _execute_with_credits."""
        orch = _make_orchestrator()
        result = _make_result(SolverStatus.OPTIMAL)

        async def _fake_execute(*args, **kwargs):
            return result

        with patch.object(orch, "_execute_with_credits", side_effect=_fake_execute) as mock_helper:
            with patch("app.services.solve_orchestrator.PSS") as mock_pss:
                mock_pss.get_int.return_value = 30
                await orch.solve_with_template(
                    problem=_make_problem(),
                    template_id="tpl_001",
                    org=_make_org(),
                    user=None,
                    request=_make_request(),
                    credits_needed=5,
                )
        mock_helper.assert_called_once()


class TestI3CreditsConsumedAfterRefundCheck:
    """CREDITS_CONSUMED.inc must not fire when a refund is triggered."""

    async def test_credits_consumed_not_incremented_on_error_result(self):
        """ERROR result triggers refund — CREDITS_CONSUMED must NOT be incremented."""
        orchestrator = _make_orchestrator()

        with patch.object(orchestrator, "_pre_pay_credits"):
            with patch.object(orchestrator, "_refund_credits"):
                with patch("app.services.solve_orchestrator.ACTIVE_SOLVES"):
                    with patch("app.services.solve_orchestrator.SOLVE_DURATION"):
                        with patch("app.services.solve_orchestrator.SOLVE_TOTAL"):
                            with patch(
                                "app.services.solve_orchestrator.CREDITS_CONSUMED"
                            ) as mock_counter:
                                result = _make_result(status=SolverStatus.ERROR)
                                await orchestrator._execute_with_credits(
                                    solve_fn=lambda: result,
                                    credits_needed=10,
                                    org=_make_org(),
                                    workspace_id=None,
                                    execution_id="exe_test",
                                    request=_make_request(),
                                    generator_label="direct",
                                    timeout_seconds=30,
                                )
                                mock_counter.inc.assert_not_called()

    async def test_credits_consumed_incremented_on_optimal_result(self):
        """OPTIMAL result → CREDITS_CONSUMED must be incremented."""
        orchestrator = _make_orchestrator()

        with patch.object(orchestrator, "_pre_pay_credits"):
            with patch.object(orchestrator, "_refund_credits"):
                with patch("app.services.solve_orchestrator.ACTIVE_SOLVES"):
                    with patch("app.services.solve_orchestrator.SOLVE_DURATION"):
                        with patch("app.services.solve_orchestrator.SOLVE_TOTAL"):
                            with patch(
                                "app.services.solve_orchestrator.CREDITS_CONSUMED"
                            ) as mock_counter:
                                result = _make_result(status=SolverStatus.OPTIMAL)
                                await orchestrator._execute_with_credits(
                                    solve_fn=lambda: result,
                                    credits_needed=10,
                                    org=_make_org(),
                                    workspace_id=None,
                                    execution_id="exe_test",
                                    request=_make_request(),
                                    generator_label="direct",
                                    timeout_seconds=30,
                                )
                                mock_counter.inc.assert_called_once_with(10)


class TestI4PSSGetIntCalledOnce:
    """PSS.get_int for SOLVER_TIMEOUT_SECONDS must be called once per public method.

    Tests use _execute_with_credits mock so the helper isn't actually called;
    we only need to check that the public method calls PSS.get_int once before
    delegating to the helper.
    """

    async def _count_get_int_calls(self, method_name: str) -> int:
        """Run the named solve method and return how many times PSS.get_int was called."""
        orch = _make_orchestrator()
        result = _make_result(status=SolverStatus.OPTIMAL)

        async def _fake_execute(*args, **kwargs):
            return result if method_name != "solve_multi_objective" else []

        with patch.object(orch, "_execute_with_credits", side_effect=_fake_execute):
            with patch("app.services.solve_orchestrator.PSS") as mock_pss:
                mock_pss.get_int.return_value = 30
                mock_pss.get_plan_config_dynamic.return_value = {
                    "allowed_features": ["sensitivity_analysis"]
                }

                if method_name == "solve_single":
                    await orch.solve_single(
                        problem=_make_problem(),
                        org=_make_org(),
                        user=None,
                        request=_make_request(),
                        credits_needed=5,
                    )
                elif method_name == "solve_multi_objective":
                    config = MagicMock(spec=MultiObjectiveConfig)
                    config.objectives = []
                    config.mode = "weighted_sum"
                    await orch.solve_multi_objective(
                        problem=_make_problem(),
                        config=config,
                        org=_make_org(),
                        user=None,
                        request=_make_request(),
                        total_credits=5,
                    )
                elif method_name == "solve_with_template":
                    await orch.solve_with_template(
                        problem=_make_problem(),
                        template_id="tpl_001",
                        org=_make_org(),
                        user=None,
                        request=_make_request(),
                        credits_needed=5,
                    )

                # Count calls with SOLVER_TIMEOUT_SECONDS as the second positional arg
                return sum(
                    1
                    for c in mock_pss.get_int.call_args_list
                    if len(c.args) >= 2 and c.args[1] == "SOLVER_TIMEOUT_SECONDS"
                )

    async def test_solve_single_calls_pss_once(self):
        """solve_single: PSS.get_int(SOLVER_TIMEOUT_SECONDS) called exactly once."""
        count = await self._count_get_int_calls("solve_single")
        assert count == 1, f"Expected 1 PSS.get_int call, got {count}"

    async def test_solve_multi_objective_calls_pss_once(self):
        """solve_multi_objective: PSS.get_int(SOLVER_TIMEOUT_SECONDS) called exactly once."""
        count = await self._count_get_int_calls("solve_multi_objective")
        assert count == 1, f"Expected 1 PSS.get_int call, got {count}"

    async def test_solve_with_template_calls_pss_once(self):
        """solve_with_template: PSS.get_int(SOLVER_TIMEOUT_SECONDS) called exactly once."""
        count = await self._count_get_int_calls("solve_with_template")
        assert count == 1, f"Expected 1 PSS.get_int call, got {count}"


class TestExecutionSourceFromRequest:
    """Provenance query params are sanitised before they can reach the DB."""

    def test_valid_values_passthrough(self):
        src = ExecutionSource.from_request("visual_builder", "builder_document", "bld_123")
        assert src.origin == "visual_builder"
        assert src.source_kind == "builder_document"
        assert src.source_id == "bld_123"

    def test_unknown_origin_collapses_to_manual(self):
        src = ExecutionSource.from_request("haxxor", "builder_document", "bld_1")
        assert src.origin == ORIGIN_MANUAL

    def test_unknown_source_kind_dropped_with_its_id(self):
        src = ExecutionSource.from_request("ai_builder", "evil_kind", "x")
        assert src.source_kind is None
        assert src.source_id is None

    def test_source_id_capped_to_column_width(self):
        src = ExecutionSource.from_request("import", "imported_file", "x" * 200)
        assert src.source_id is not None
        assert len(src.source_id) <= 64

    def test_defaults_to_manual(self):
        src = ExecutionSource.from_request(None)
        assert src.origin == ORIGIN_MANUAL
        assert src.source_kind is None
        assert src.source_id is None


class TestProvenancePersistence:
    """Solve paths persist a ModelExecution row carrying their provenance."""

    @staticmethod
    def _capture_rows(orch: SolveOrchestrator) -> list:
        captured: list = []
        orch.db.add.side_effect = lambda row: captured.append(row)
        return captured

    async def test_template_solve_persists_template_origin(self):
        # CONTRACT-TEST: template solves leave a navigable execution row (origin=template)
        orch = _make_orchestrator()
        result = _make_result(SolverStatus.OPTIMAL)
        result.to_result_data.return_value = {}
        result.objective_value = 1.0
        captured = self._capture_rows(orch)

        async def _fake_execute(*args, **kwargs):
            return result

        with patch.object(orch, "_execute_with_credits", side_effect=_fake_execute):
            with patch("app.services.solve_orchestrator.PSS") as mock_pss:
                mock_pss.get_int.return_value = 30
                await orch.solve_with_template(
                    problem=_make_problem(),
                    template_id="tpl_xyz",
                    org=_make_org(),
                    user=None,
                    request=_make_request(),
                    credits_needed=5,
                )

        rows = [r for r in captured if hasattr(r, "origin")]
        assert rows, "template solve persisted no ModelExecution row"
        assert rows[-1].origin == ORIGIN_TEMPLATE
        assert rows[-1].source_kind == "template"
        assert rows[-1].source_id == "tpl_xyz"

    async def test_solve_single_persists_given_source(self):
        orch = _make_orchestrator()
        result = _make_result(SolverStatus.OPTIMAL)
        result.to_result_data.return_value = {}
        result.objective_value = 1.0
        captured = self._capture_rows(orch)

        async def _fake_execute(*args, **kwargs):
            return result

        src = ExecutionSource(
            origin="visual_builder", source_kind="builder_document", source_id="bld_9"
        )
        with patch.object(orch, "_execute_with_credits", side_effect=_fake_execute):
            with patch("app.services.solve_orchestrator.PSS") as mock_pss:
                mock_pss.get_int.return_value = 30
                mock_pss.get_plan_config_dynamic.return_value = {"allowed_features": []}
                await orch.solve_single(
                    problem=_make_problem(),
                    org=_make_org(),
                    user=None,
                    request=_make_request(),
                    credits_needed=5,
                    source=src,
                )

        rows = [r for r in captured if hasattr(r, "origin")]
        assert rows, "solve_single persisted no ModelExecution row"
        assert rows[-1].origin == "visual_builder"
        assert rows[-1].source_kind == "builder_document"
        assert rows[-1].source_id == "bld_9"

    async def test_multi_objective_persists_execution(self):
        # CONTRACT-TEST: multi-objective solves leave an execution row in history
        orch = _make_orchestrator()
        captured = self._capture_rows(orch)

        async def _fake_execute(*args, **kwargs):
            return []

        with patch.object(orch, "_execute_with_credits", side_effect=_fake_execute):
            with patch("app.services.solve_orchestrator.PSS") as mock_pss:
                mock_pss.get_int.return_value = 30
                config = MagicMock(spec=MultiObjectiveConfig)
                config.objectives = []
                config.mode = "weighted_sum"
                await orch.solve_multi_objective(
                    problem=_make_problem(),
                    config=config,
                    org=_make_org(),
                    user=None,
                    request=_make_request(),
                    total_credits=5,
                    source=ExecutionSource(origin="visual_builder"),
                )

        rows = [r for r in captured if hasattr(r, "origin")]
        assert rows, "multi-objective solve persisted no ModelExecution row"
        assert rows[-1].origin == "visual_builder"
        assert "multi_objective" in rows[-1].result_data
