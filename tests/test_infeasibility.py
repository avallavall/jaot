"""Tests for P2 — infeasibility explainer (IIS deletion filtering + LLM).

Two layers, no mocking of the solver:
- ``compute_iis`` runs against the real SCIP adapter (registered by the autouse
  conftest fixture). It must return exactly the conflicting constraints/bounds, drop
  redundant ones, honour the constraint cap + time budget, and never present a
  feasible subset as the IIS (the minimality contract).
- ``explain_infeasibility`` + ``build_infeasibility_explanation_prompt`` are exercised
  with the Anthropic client mocked at the provider boundary (mirrors
  ``test_explanation_service.py``).
"""

from unittest.mock import MagicMock, patch

import pytest

from app.domains.solver.services.infeasibility import compute_iis
from app.domains.solver.services.solver_service import SolverService
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverStatus,
    Variable,
    VariableType,
)
from app.services.llm.errors import LLMStatusCode
from app.services.llm.prompt_templates import (
    INFEASIBILITY_EXPLANATION_SYSTEM_PROMPT,
    build_infeasibility_explanation_prompt,
)

# --- Shared problem builders -------------------------------------------------


def _conflicting_constraints_problem(extra_constraints=None):
    """x >= 10 AND x <= 5 — infeasible purely by two constraints.

    x carries an (irrelevant, redundant) lower_bound=0 so the tests can prove the
    redundant bound is dropped from the IIS rather than reported as part of it.
    """
    constraints = [
        Constraint(name="floor", expression="x >= 10"),
        Constraint(name="ceiling", expression="x <= 5"),
    ]
    constraints.extend(extra_constraints or [])
    return OptimizationProblem(
        name="infeasible_constraints",
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
        variables=[Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0)],
        constraints=constraints,
    )


def _solver() -> SolverService:
    return SolverService()


# --- compute_iis -------------------------------------------------------------


class TestComputeIIS:
    def test_returns_exactly_the_conflicting_constraints(self):
        analysis = compute_iis(
            _conflicting_constraints_problem(),
            _solver(),
            max_constraints=150,
            time_budget_s=20.0,
        )
        assert analysis.method == "iis"
        assert set(analysis.iis_constraints) == {"floor", "ceiling"}
        assert analysis.conflict_type == "constraint"
        # The redundant lower_bound=0 is NOT part of the conflict.
        assert analysis.iis_variable_bounds == []

    def test_drops_redundant_constraints(self):
        """A non-conflicting constraint must never appear in the IIS."""
        analysis = compute_iis(
            _conflicting_constraints_problem(
                extra_constraints=[Constraint(name="slack", expression="x <= 500")]
            ),
            _solver(),
            max_constraints=150,
            time_budget_s=20.0,
        )
        assert set(analysis.iis_constraints) == {"floor", "ceiling"}
        assert "slack" not in analysis.iis_constraints

    def test_iis_is_minimal_removing_any_member_restores_feasibility(self):
        # CONTRACT-TEST: IIS minimality — dropping any single IIS member makes the
        # model feasible again. A non-minimal set (e.g. one that keeps a redundant
        # constraint) would break this invariant.
        problem = _conflicting_constraints_problem(
            extra_constraints=[Constraint(name="slack", expression="x <= 500")]
        )
        solver = _solver()
        analysis = compute_iis(problem, solver, max_constraints=150, time_budget_s=20.0)

        iis_names = set(analysis.iis_constraints)
        assert iis_names  # non-empty

        # The full IIS subset alone is still infeasible.
        iis_only = [c for c in problem.constraints if c.name in iis_names]
        full = problem.model_copy(update={"constraints": iis_only})
        assert solver.solve(full).status == SolverStatus.INFEASIBLE

        # Removing any one member restores feasibility — proves minimality.
        for victim in iis_names:
            kept = [c for c in iis_only if c.name != victim]
            candidate = problem.model_copy(update={"constraints": kept})
            assert solver.solve(candidate).status != SolverStatus.INFEASIBLE

    def test_mixed_constraint_and_bound_conflict(self):
        """A finite variable bound that participates in the conflict is reported."""
        problem = OptimizationProblem(
            name="mixed_conflict",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
            variables=[Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=10)],
            constraints=[Constraint(name="ceiling", expression="x <= 5")],
        )
        analysis = compute_iis(problem, _solver(), max_constraints=150, time_budget_s=20.0)
        assert analysis.method == "iis"
        assert analysis.conflict_type == "mixed"
        assert "ceiling" in analysis.iis_constraints
        assert "x >= 10.0" in analysis.iis_variable_bounds

    def test_pure_bound_conflict(self):
        """lb > ub on a single variable — infeasible by bounds alone."""
        problem = OptimizationProblem(
            name="bound_conflict",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=10, upper_bound=5)
            ],
            constraints=[],
        )
        analysis = compute_iis(problem, _solver(), max_constraints=150, time_budget_s=20.0)
        assert analysis.method == "iis"
        assert analysis.conflict_type == "bound"
        assert analysis.iis_constraints == []
        assert sorted(analysis.iis_variable_bounds) == ["x <= 5.0", "x >= 10.0"]

    def test_aborts_to_llm_only_when_over_constraint_cap(self):
        analysis = compute_iis(
            _conflicting_constraints_problem(),
            _solver(),
            max_constraints=1,  # 2 constraints > cap
            time_budget_s=20.0,
        )
        assert analysis.method == "llm_only"
        assert analysis.conflict_type == "unknown"
        assert analysis.iis_constraints == []
        assert "too large" in (analysis.note or "")

    def test_aborts_to_llm_only_when_time_budget_exceeded(self):
        # A zero budget is exceeded right after the (mandatory) infeasibility
        # confirmation solve, before any deletion-filtering re-solve completes.
        analysis = compute_iis(
            _conflicting_constraints_problem(),
            _solver(),
            max_constraints=150,
            time_budget_s=0.0,
        )
        assert analysis.method == "llm_only"
        assert "budget" in (analysis.note or "").lower()

    def test_feasible_model_reports_nothing_to_explain(self):
        problem = OptimizationProblem(
            name="feasible",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
            variables=[Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0)],
            constraints=[Constraint(name="cap", expression="x <= 5")],
        )
        analysis = compute_iis(problem, _solver(), max_constraints=150, time_budget_s=20.0)
        assert analysis.iis_constraints == []
        assert "feasible" in (analysis.note or "").lower()


# --- build_infeasibility_explanation_prompt ----------------------------------

FORMULATION = {
    "name": "infeasible_lp",
    "variables": [{"name": "x", "type": "continuous"}],
    "constraints": [
        {"name": "floor", "expression": "x >= 10"},
        {"name": "ceiling", "expression": "x <= 5"},
    ],
    "objective": {"sense": "maximize", "expression": "x"},
}
IIS = {
    "iis_constraints": ["floor", "ceiling"],
    "iis_variable_bounds": [],
    "conflict_type": "constraint",
    "method": "iis",
    "note": None,
}


class TestBuildInfeasibilityPrompt:
    def test_grounds_in_the_iis_when_available(self):
        prompt = build_infeasibility_explanation_prompt(FORMULATION, IIS)
        assert "Irreducible Infeasible Set" in prompt
        assert "floor" in prompt
        assert "ceiling" in prompt
        assert "heuristically" not in prompt.lower()

    def test_flags_heuristic_when_no_iis(self):
        prompt = build_infeasibility_explanation_prompt(FORMULATION, None)
        assert "heuristically" in prompt.lower()
        assert "best guess" in prompt.lower()

    def test_flags_heuristic_for_llm_only_method(self):
        llm_only = {"method": "llm_only", "note": "model too large for exact IIS"}
        prompt = build_infeasibility_explanation_prompt(FORMULATION, llm_only)
        assert "heuristically" in prompt.lower()
        assert "model too large" in prompt


# --- explain_infeasibility (mocked Anthropic) --------------------------------


def _text_events(text: str):
    events = []
    for chunk in (text[i : i + 8] for i in range(0, len(text), 8)):
        event = MagicMock()
        event.type = "content_block_delta"
        event.delta = MagicMock()
        event.delta.type = "text_delta"
        event.delta.text = chunk
        events.append(event)
    return events


class _MockStreamContext:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for event in self.events:
            yield event


class TestExplainInfeasibility:
    @pytest.mark.asyncio
    async def test_yields_status_then_deltas_then_done(self):
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(
            return_value=_MockStreamContext(
                _text_events("Constraints floor and ceiling conflict; relax one.")
            )
        )

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            from app.services.llm.explanation_service import explain_infeasibility

            events = []
            async for event in explain_infeasibility([], FORMULATION, IIS, "claude-sonnet-4-6"):
                events.append(event)

        assert events[0]["type"] == "status"
        assert events[0]["code"] == LLMStatusCode.EXPLAINING
        types = [e["type"] for e in events]
        assert "delta" in types
        assert types[-1] == "done"

    @pytest.mark.asyncio
    async def test_uses_infeasibility_system_prompt_and_grounded_turn(self):
        captured: dict = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return _MockStreamContext(_text_events("ok"))

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(side_effect=_capture)

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            from app.services.llm.explanation_service import explain_infeasibility

            async for _ in explain_infeasibility([], FORMULATION, IIS, "claude-sonnet-4-6"):
                pass

        assert captured["system"] == INFEASIBILITY_EXPLANATION_SYSTEM_PROMPT
        last_user_turn = captured["messages"][-1]
        assert last_user_turn["role"] == "user"
        assert "floor" in last_user_turn["content"]
