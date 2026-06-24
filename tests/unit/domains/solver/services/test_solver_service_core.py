"""Direct unit tests for SolverService core decision logic — Phase 12.5 Plan 06.

Broadens the solver_service.py mutation surface (Plan 02 flagged it shallow: only
~12 covered mutants over ~408 LOC because the solver test selection exercises
``solve()`` via SCIP but never the multi-objective scalarization helpers or the
``resolve_effective_solver`` auto-routing delegation). These pure, DB-free unit
tests cover that decision logic directly so mutmut can surface — and these tests
can kill — the previously-uncovered routing/Pareto/scalarization mutants.

No DB, no SCIP, no pyscipopt import (import-linter contract
``solver-services-no-pyscipopt`` stays green — these tests live in tests/).
``resolve_effective_solver``'s "auto" branch is exercised with the worker probe
patched so the routing decision is deterministic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domains.solver.adapters import registry
from app.domains.solver.adapters.base import DEFAULT_SOLVER_NAME
from app.domains.solver.services.auto_router import (
    AUTO_REASON_FALLBACK,
    AUTO_REASON_LP,
    AUTO_REASON_QUADRATIC,
)
from app.domains.solver.services.solver_service import (
    SolverService,
    _build_weighted_objective,
    _compute_objective_value,
    _emit_expression_string,
)
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    OptimizationResult,
    ParetoPoint,
    SolverStatus,
    Variable,
    VariableType,
)

_PROBE_TARGET = "app.domains.solver.services.worker_health._probe_hexaly_worker"


def _lp_problem() -> OptimizationProblem:
    return OptimizationProblem(
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0, upper_bound=10.0),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0.0, upper_bound=10.0),
        ],
        objective=Objective(expression="2*x + 3*y", sense=ObjectiveSense.MAXIMIZE),
        constraints=[Constraint(expression="x + y <= 5", name="budget")],
    )


def _quadratic_problem() -> OptimizationProblem:
    return OptimizationProblem(
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0, upper_bound=10.0),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0.0, upper_bound=10.0),
        ],
        objective=Objective(expression="x * y", sense=ObjectiveSense.MAXIMIZE),
        constraints=[Constraint(expression="x + y <= 10", name="budget")],
    )


# ---------------------------------------------------------------------------
# resolve_effective_solver — the "auto" delegation + explicit/default passthrough
# (core routing logic; the API layer relies on this to surface solver + reason).
# ---------------------------------------------------------------------------


class TestResolveEffectiveSolver:
    def test_auto_lp_delegates_to_router_and_propagates_triple(self):
        """``auto`` + LP problem -> ('highs', lp_routed_to_highs, False) via router."""
        svc = SolverService()
        name, reason, fallback = svc.resolve_effective_solver("auto", _lp_problem())
        assert name == "highs"
        assert reason == AUTO_REASON_LP
        assert fallback is False

    def test_auto_quadratic_worker_up_routes_hexaly(self):
        """``auto`` + quadratic + worker UP -> hexaly, reason propagated."""
        svc = SolverService()
        with patch(_PROBE_TARGET, return_value=(True, None)):
            name, reason, fallback = svc.resolve_effective_solver("auto", _quadratic_problem())
        assert name == "hexaly"
        assert reason == AUTO_REASON_QUADRATIC
        assert fallback is False

    def test_auto_quadratic_worker_down_sets_fallback_true(self):
        """``auto`` + quadratic + worker DOWN -> scip with fallback_triggered True.

        Pins the fallback bool the API layer turns into a D-11 ``warning`` field.
        """
        svc = SolverService()
        with patch(_PROBE_TARGET, return_value=(False, "probe_off")):
            name, reason, fallback = svc.resolve_effective_solver("auto", _quadratic_problem())
        assert name == "scip"
        assert reason == AUTO_REASON_FALLBACK
        assert fallback is True

    def test_explicit_name_passthrough_no_reason(self):
        """An explicit solver name is returned verbatim with reason=None, fallback=False."""
        svc = SolverService()
        name, reason, fallback = svc.resolve_effective_solver("highs", _lp_problem())
        assert name == "highs"
        assert reason is None
        assert fallback is False

    def test_none_falls_back_to_instance_default(self):
        """None requested name -> the service's configured default (not 'auto' routing)."""
        svc = SolverService(solver_name="scip")
        name, reason, fallback = svc.resolve_effective_solver(None, _lp_problem())
        assert name == "scip"
        assert name == DEFAULT_SOLVER_NAME
        assert reason is None
        assert fallback is False

    def test_explicit_name_is_not_overridden_by_default(self):
        """A non-default explicit name must win over the instance default."""
        svc = SolverService(solver_name="scip")
        name, _reason, _fallback = svc.resolve_effective_solver("highs", _lp_problem())
        assert name == "highs"


# ---------------------------------------------------------------------------
# solve() dispatch + warm-start passthrough, and the get_solver_service factory.
# Uses a registered mock adapter (the solver collaborator is mockable; the DB
# boundary is NOT touched — no Session mock, matching test_solve_orchestrator.py).
# ---------------------------------------------------------------------------


class TestSolveDispatch:
    def test_solve_forwards_warm_start_to_adapter(self):
        """solve() must pass warm_start_solution through to adapter.solve(warm_start=...).

        Kills the mutant that hard-codes ``warm_start=None`` on the adapter call
        (dropping warm-start support silently). Asserts the exact value forwarded.
        """
        svc = SolverService()
        mock_adapter = MagicMock()
        mock_adapter.solve.return_value = OptimizationResult(
            status=SolverStatus.OPTIMAL, solve_time_seconds=0.0, objective_value=1.0, solution={}
        )
        warm = {"x": 3.0, "y": 4.0}
        problem = _lp_problem()
        registry.register("mock_warm", mock_adapter)
        try:
            svc.solve(problem, warm_start_solution=warm, solver_name="mock_warm")
        finally:
            registry._adapters.pop("mock_warm", None)
        # The adapter must have been called with the SAME warm-start dict, not None.
        _, kwargs = mock_adapter.solve.call_args
        assert kwargs.get("warm_start") == warm
        assert kwargs.get("warm_start") is not None

    def test_solve_dispatches_to_requested_solver_name(self):
        """solve(solver_name=X) resolves adapter X from the registry (routing)."""
        svc = SolverService()
        mock_adapter = MagicMock()
        mock_adapter.solve.return_value = OptimizationResult(
            status=SolverStatus.OPTIMAL, solve_time_seconds=0.0, objective_value=0.0, solution={}
        )
        registry.register("mock_dispatch", mock_adapter)
        try:
            svc.solve(_lp_problem(), solver_name="mock_dispatch")
        finally:
            registry._adapters.pop("mock_dispatch", None)
        mock_adapter.solve.assert_called_once()


class TestGetSolverServiceFactory:
    def test_explicit_name_sets_instance_default(self):
        """get_solver_service('highs') -> a SolverService whose default is 'highs'.

        Kills the mutant that passes ``solver_name=None`` inside the
        ``if solver_name is not None`` branch (which would silently ignore the
        caller's explicit choice and fall back to the global default).
        """
        from app.domains.solver.services.solver_service import get_solver_service

        svc = get_solver_service("highs")
        assert svc._default_solver_name == "highs"

    def test_none_uses_global_default(self):
        """get_solver_service(None) -> a SolverService at the global default name."""
        from app.domains.solver.services.solver_service import get_solver_service

        svc = get_solver_service(None)
        assert svc._default_solver_name == DEFAULT_SOLVER_NAME


# ---------------------------------------------------------------------------
# _is_nondominated — Pareto dominance with per-objective sense.
# ---------------------------------------------------------------------------


class TestIsNondominated:
    def test_empty_front_is_nondominated(self):
        svc = SolverService()
        assert svc._is_nondominated(1.0, 1.0, []) is True

    def test_minimize_strictly_dominated_point_rejected(self):
        """MIN/MIN: an existing (1,1) dominates a new (2,2) -> not nondominated."""
        svc = SolverService()
        existing = [ParetoPoint(f1=1.0, f2=1.0, solution={}, objective_values={})]
        assert svc._is_nondominated(2.0, 2.0, existing) is False

    def test_minimize_better_point_is_nondominated(self):
        """MIN/MIN: a new (0.5,0.5) is better than existing (1,1) -> nondominated."""
        svc = SolverService()
        existing = [ParetoPoint(f1=1.0, f2=1.0, solution={}, objective_values={})]
        assert svc._is_nondominated(0.5, 0.5, existing) is True

    def test_minimize_tie_without_strict_is_nondominated(self):
        """MIN/MIN: an exact tie (1,1) vs (1,1) is NOT dominated (needs strict<).

        Kills a mutant that flips the strict ``<`` to ``<=`` (which would wrongly
        treat an equal point as dominated).
        """
        svc = SolverService()
        existing = [ParetoPoint(f1=1.0, f2=1.0, solution={}, objective_values={})]
        assert svc._is_nondominated(1.0, 1.0, existing) is True

    def test_minimize_weakly_dominated_with_one_strict_rejected(self):
        """MIN/MIN: existing (1,1) vs new (1,2) — equal on f1, worse on f2 -> dominated."""
        svc = SolverService()
        existing = [ParetoPoint(f1=1.0, f2=1.0, solution={}, objective_values={})]
        assert svc._is_nondominated(1.0, 2.0, existing) is False

    def test_minimize_weak_dominance_tie_on_f2_rejected(self):
        """MIN/MIN: existing (0,5) vs new (1,5) — strictly better on f1, TIE on f2 -> dominated.

        Pins the WEAK-dominance ``<=`` on the f2 ``dom2`` check (kills the mutant
        that strengthens ``pt.f2 <= new_f2`` to ``pt.f2 < new_f2``). With the
        mutant, the tie on f2 makes dom2 False and the genuinely-dominated new
        point would wrongly be kept as nondominated. Domination here is real:
        (0,5) is at-least-as-good on both and strictly better on f1.
        """
        svc = SolverService()
        existing = [ParetoPoint(f1=0.0, f2=5.0, solution={}, objective_values={})]
        assert svc._is_nondominated(1.0, 5.0, existing) is False

    def test_minimize_weak_dominance_tie_on_f1_rejected(self):
        """MIN/MIN: existing (5,0) vs new (5,1) — TIE on f1, strictly better on f2 -> dominated.

        Symmetric guard pinning the WEAK ``<=`` on the f1 ``dom1`` check (kills
        the ``pt.f1 <= new_f1`` -> ``pt.f1 < new_f1`` mutant).
        """
        svc = SolverService()
        existing = [ParetoPoint(f1=5.0, f2=0.0, solution={}, objective_values={})]
        assert svc._is_nondominated(5.0, 1.0, existing) is False

    def test_maximize_weak_dominance_tie_on_one_objective_rejected(self):
        """MAX/MAX: existing (9,5) vs new (8,5) — strictly better on f1, TIE on f2 -> dominated.

        Symmetric guard for the f2 ``dom2`` weak ``>=`` in the MAXIMIZE branch.
        """
        svc = SolverService()
        existing = [ParetoPoint(f1=9.0, f2=5.0, solution={}, objective_values={})]
        assert (
            svc._is_nondominated(
                8.0,
                5.0,
                existing,
                sense1=ObjectiveSense.MAXIMIZE,
                sense2=ObjectiveSense.MAXIMIZE,
            )
            is False
        )

    def test_maximize_dominance_direction_flips(self):
        """MAX/MAX: higher is better. Existing (5,5) dominates new (3,3)."""
        svc = SolverService()
        existing = [ParetoPoint(f1=5.0, f2=5.0, solution={}, objective_values={})]
        assert (
            svc._is_nondominated(
                3.0,
                3.0,
                existing,
                sense1=ObjectiveSense.MAXIMIZE,
                sense2=ObjectiveSense.MAXIMIZE,
            )
            is False
        )

    def test_maximize_better_point_is_nondominated(self):
        """MAX/MAX: a new (9,9) beats existing (5,5) -> nondominated."""
        svc = SolverService()
        existing = [ParetoPoint(f1=5.0, f2=5.0, solution={}, objective_values={})]
        assert (
            svc._is_nondominated(
                9.0,
                9.0,
                existing,
                sense1=ObjectiveSense.MAXIMIZE,
                sense2=ObjectiveSense.MAXIMIZE,
            )
            is True
        )

    def test_maximize_exact_tie_is_nondominated(self):
        """MAX/MAX: an exact tie (5,5) vs (5,5) is NOT dominated (needs strict>).

        Kills the strict ``>`` -> ``>=`` mutants on BOTH objectives in the
        MAXIMIZE branch (``_is_nondominated`` strict1/strict2): with the mutant,
        an equal point reads as strictly-better and the tie is wrongly treated as
        dominated. Real semantics: equal-on-all is nondominated (no strict gain).
        """
        svc = SolverService()
        existing = [ParetoPoint(f1=5.0, f2=5.0, solution={}, objective_values={})]
        assert (
            svc._is_nondominated(
                5.0,
                5.0,
                existing,
                sense1=ObjectiveSense.MAXIMIZE,
                sense2=ObjectiveSense.MAXIMIZE,
            )
            is True
        )

    def test_maximize_weakly_dominated_with_one_strict_rejected(self):
        """MAX/MAX: existing (5,5) vs new (5,3) — tie on f1, worse on f2 -> dominated.

        Pins strict2 in the MAX branch: f1 ties (strict1 False) so domination
        hinges entirely on strict2 being True for the genuinely-worse f2.
        """
        svc = SolverService()
        existing = [ParetoPoint(f1=5.0, f2=5.0, solution={}, objective_values={})]
        assert (
            svc._is_nondominated(
                5.0,
                3.0,
                existing,
                sense1=ObjectiveSense.MAXIMIZE,
                sense2=ObjectiveSense.MAXIMIZE,
            )
            is False
        )

    def test_tradeoff_point_is_nondominated(self):
        """MIN/MIN: (0,5) vs existing (5,0) — neither dominates -> nondominated."""
        svc = SolverService()
        existing = [ParetoPoint(f1=5.0, f2=0.0, solution={}, objective_values={})]
        assert svc._is_nondominated(0.0, 5.0, existing) is True


# ---------------------------------------------------------------------------
# _compute_objective_value — linear + bilinear evaluation against a solution dict.
# ---------------------------------------------------------------------------


class TestComputeObjectiveValue:
    def _result(self, solution: dict[str, float]) -> OptimizationResult:
        return OptimizationResult(
            status=SolverStatus.OPTIMAL,
            solve_time_seconds=0.01,
            objective_value=0.0,
            solution=solution,
        )

    def test_linear_with_constant(self):
        """3 + 2*x + 4*y at x=1,y=2 -> 3 + 2 + 8 = 13."""
        svc = SolverService()
        obj = Objective(expression="3 + 2*x + 4*y", sense=ObjectiveSense.MINIMIZE)
        val = _compute_objective_value(
            self._result({"x": 1.0, "y": 2.0}), obj, svc.parser, ["x", "y"]
        )
        assert val == pytest.approx(13.0)

    def test_bilinear_term(self):
        """2*x*y at x=3,y=5 -> 30 (the two-variable term branch)."""
        svc = SolverService()
        obj = Objective(expression="2*x*y", sense=ObjectiveSense.MINIMIZE)
        val = _compute_objective_value(
            self._result({"x": 3.0, "y": 5.0}), obj, svc.parser, ["x", "y"]
        )
        assert val == pytest.approx(30.0)

    def test_missing_variable_defaults_to_zero(self):
        """A linear variable absent from the solution dict contributes 0 (.get default)."""
        svc = SolverService()
        obj = Objective(expression="10*x + 7*y", sense=ObjectiveSense.MINIMIZE)
        val = _compute_objective_value(self._result({"x": 2.0}), obj, svc.parser, ["x", "y"])
        assert val == pytest.approx(20.0)

    def test_bilinear_missing_second_variable_contributes_zero(self):
        """A bilinear term whose 2nd variable is absent contributes exactly 0.

        Kills the mutants that change the bilinear ``.get(v2, 0.0)`` default to
        ``None`` (TypeError) or ``1.0`` (the term would wrongly contribute
        ``coeff * v1 * 1.0`` instead of 0). The whole quadratic objective value
        must be 0 here because the only term is the bilinear one and y is missing.
        """
        svc = SolverService()
        obj = Objective(expression="5*x*y", sense=ObjectiveSense.MINIMIZE)
        val = _compute_objective_value(self._result({"x": 4.0}), obj, svc.parser, ["x", "y"])
        assert val == pytest.approx(0.0)

    def test_bilinear_missing_first_variable_contributes_zero(self):
        """A bilinear term whose 1st variable is absent contributes exactly 0.

        Symmetric guard for the ``.get(v1, 0.0)`` default (kills the v1 default
        mutants). x absent -> 0 * y = 0 regardless of y.
        """
        svc = SolverService()
        obj = Objective(expression="5*x*y", sense=ObjectiveSense.MINIMIZE)
        val = _compute_objective_value(self._result({"y": 7.0}), obj, svc.parser, ["x", "y"])
        assert val == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _build_weighted_objective + _emit_expression_string — scalarization helpers.
# ---------------------------------------------------------------------------


class TestScalarizationHelpers:
    def test_weighted_objective_is_minimize(self):
        """Scalarized objective is always MINIMIZE (the orchestrator convention)."""
        obj1 = Objective(expression="x", sense=ObjectiveSense.MINIMIZE)
        obj2 = Objective(expression="y", sense=ObjectiveSense.MINIMIZE)
        scal = _build_weighted_objective(obj1, obj2, 0.5, 0.5)
        assert scal.sense == ObjectiveSense.MINIMIZE

    def test_weighted_objective_negates_maximize_source(self):
        """A MAXIMIZE source gets a negative sign so the combined problem minimizes.

        Kills the sign mutant (1.0 vs -1.0 selection on objective sense).
        """
        obj_min = Objective(expression="x", sense=ObjectiveSense.MINIMIZE)
        obj_max = Objective(expression="y", sense=ObjectiveSense.MAXIMIZE)
        scal = _build_weighted_objective(obj_min, obj_max, 1.0, 1.0)
        # w1*sign1 = 1.0*(+1.0) = 1.0 for the MINIMIZE source;
        # w2*sign2 = 1.0*(-1.0) = -1.0 for the MAXIMIZE source.
        assert "(1.0) * (x)" in scal.expression
        assert "(-1.0) * (y)" in scal.expression

    def test_emit_expression_roundtrip_linear_and_bilinear(self):
        """_emit_expression_string renders constant + linear + bilinear terms re-parseably."""
        svc = SolverService()
        parsed = svc.parser.parse_expression("3 + 2*x + 4*x*y", known_variables=["x", "y"])
        emitted = _emit_expression_string(parsed)
        # Re-parse the emitted string and evaluate at x=1,y=2: 3 + 2 + 4*1*2 = 13.
        reparsed = svc.parser.parse_expression(emitted, known_variables=["x", "y"])
        value = reparsed.constant
        for term in reparsed.terms:
            if len(term.variables) == 1:
                value += term.coefficient * {"x": 1.0, "y": 2.0}[term.variables[0]]
            elif len(term.variables) == 2:
                v1, v2 = term.variables
                value += term.coefficient * {"x": 1.0, "y": 2.0}[v1] * {"x": 1.0, "y": 2.0}[v2]
        assert value == pytest.approx(13.0)
