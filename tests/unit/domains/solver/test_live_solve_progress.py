"""Live Solve — per-incumbent progress streaming via the ``on_progress`` callback.

Covers the additive, contract-safe wiring added for Live Solve:
- SCIP fires ``on_progress`` with a ``ProgressPoint`` for each new incumbent.
- ``solve(on_progress=None)`` is a perfect no-op (existing behaviour unchanged).
- ``capabilities.supports_progress`` is True only for SCIP.
- ``SolverService.solve`` forwards ``on_progress`` to the adapter.
- The async task's progress publisher emits a ``solve_progress`` event on the
  existing ``ws:execution:{id}`` channel.
"""

import pytest

from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    OptimizationResult,
    ProgressPoint,
    SolverStatus,
    Variable,
    VariableType,
)


def _milp_with_incumbents() -> OptimizationProblem:
    """A tiny MILP that yields at least one incumbent (BESTSOLFOUND) when solved."""
    return OptimizationProblem(
        name="milp_progress",
        variables=[
            Variable(name="x", type=VariableType.INTEGER, lower_bound=0, upper_bound=10),
            Variable(name="y", type=VariableType.INTEGER, lower_bound=0, upper_bound=10),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + 2*y"),
        constraints=[Constraint(name="sum_limit", expression="x + y <= 4")],
    )


@pytest.mark.unit
def test_scip_solve_streams_each_incumbent() -> None:
    """SCIPAdapter.solve() must invoke on_progress with a ProgressPoint per incumbent."""
    from app.domains.solver.adapters.scip import SCIPAdapter

    points: list[ProgressPoint] = []
    result = SCIPAdapter().solve(_milp_with_incumbents(), on_progress=points.append)

    assert result.status == SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(8.0, abs=1e-6)
    assert len(points) >= 1, "on_progress must fire at least once for a MILP with an incumbent"
    last = points[-1]
    assert isinstance(last, ProgressPoint)
    assert last.iteration >= 1
    # primal_bound is finite (the handler skips the ±1e20 'no bound yet' sentinel)
    assert last.primal_bound == pytest.approx(last.objective)


@pytest.mark.unit
def test_scip_solve_on_progress_none_is_noop() -> None:
    """# CONTRACT-TEST: solve(on_progress=None) is a no-op vs the prior behaviour.

    The same problem must solve to the same status/objective with the callback
    omitted, and progress_history must still be populated (Live Solve must not
    regress the existing convergence-chart path).
    """
    from app.domains.solver.adapters.scip import SCIPAdapter

    result = SCIPAdapter().solve(_milp_with_incumbents())

    assert result.status == SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(8.0, abs=1e-6)
    assert result.progress_history, "progress_history must still be populated when on_progress=None"


@pytest.mark.unit
def test_supports_progress_capability_matrix() -> None:
    """Only SCIP advertises supports_progress; HiGHS and Hexaly do not.

    Reads the class-level ``capabilities`` so HexalyAdapter.__init__ (which loads a
    platform license) is never invoked.
    """
    from app.domains.solver.adapters.hexaly import HexalyAdapter
    from app.domains.solver.adapters.highs import HiGHSAdapter
    from app.domains.solver.adapters.scip import SCIPAdapter

    assert SCIPAdapter.capabilities.supports_progress is True
    assert HiGHSAdapter.capabilities.supports_progress is False
    assert HexalyAdapter.capabilities.supports_progress is False


@pytest.mark.unit
def test_solver_service_forwards_on_progress() -> None:
    """SolverService.solve must forward on_progress to the resolved adapter."""
    from app.domains.solver.adapters import registry
    from app.domains.solver.adapters.base import SolverCapabilities
    from app.domains.solver.services.solver_service import SolverService

    class _RecordingAdapter:
        capabilities = SolverCapabilities(
            name="_progress_probe",
            supports_continuous=True,
            supports_integer=True,
            supports_binary=True,
            supports_quadratic=False,
            supports_sensitivity=False,
            supports_warm_start=False,
            supports_multi_objective=False,
            supports_progress=True,
        )

        def __init__(self) -> None:
            self.received_on_progress: object = "UNSET"

        def is_available(self) -> bool:
            return True

        def solve(self, problem, *, warm_start=None, on_progress=None) -> OptimizationResult:
            self.received_on_progress = on_progress
            return OptimizationResult(status=SolverStatus.OPTIMAL, solve_time_seconds=0.0)

    fake = _RecordingAdapter()
    registry.register("_progress_probe", fake)

    def _cb(_point: ProgressPoint) -> None:  # pragma: no cover - identity sentinel only
        return None

    SolverService(solver_name="_progress_probe").solve(_milp_with_incumbents(), on_progress=_cb)

    assert fake.received_on_progress is _cb, "SolverService must pass on_progress through unchanged"


@pytest.mark.unit
def test_async_progress_publisher_emits_solve_progress_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The async on_progress publisher emits a solve_progress event for the execution.

    Publishing goes to the existing ws:execution:{id} channel via _publish_ws_event
    (channel keyed on the first arg). We capture that call instead of touching Redis.
    """
    from app.domains.solver.tasks import solve_tasks

    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        solve_tasks, "_publish_ws_event", lambda exec_id, data: captured.append((exec_id, data))
    )

    publisher = solve_tasks._make_solve_progress_publisher("exe_live_test")
    publisher(
        ProgressPoint(
            iteration=2,
            node=5,
            objective=8.0,
            primal_bound=8.0,
            dual_bound=8.0,
            gap=0.0,
            elapsed_seconds=0.12,
        )
    )

    assert len(captured) == 1
    exec_id, data = captured[0]
    assert exec_id == "exe_live_test"
    assert data["type"] == "solve_progress"
    assert data["execution_id"] == "exe_live_test"
    assert data["objective"] == 8.0
    assert data["gap"] == 0.0
