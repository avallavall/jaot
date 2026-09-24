"""JAOS adapter: what it returns, and what it does with the JAOS calls it makes.

The answers every solver must agree on (objective constant, binary bounds, time
limits, unbounded models) are in
``test_every_solver_solves_the_model_it_was_given.py``, which runs JAOS too.
This file covers what only this adapter does: sensitivity against HiGHS, MIP
starts, the progress trace, the log, the version string, a missing library, and
an exception raised by a signal handler during the solve.
"""

from __future__ import annotations

import logging
import random
import re
import signal
import sys
import time

import pytest

from app.domains.solver.adapters.highs import HiGHSAdapter
from app.domains.solver.adapters.jaos import JAOSAdapter
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    ProgressPoint,
    SolverOptions,
    SolverStatus,
    Variable,
    VariableType,
)

pytestmark = pytest.mark.unit


def _lp(sense: ObjectiveSense) -> OptimizationProblem:
    """Two rows binding at the optimum (x = 3.5, y = 2.5), both with a price."""
    return OptimizationProblem(
        variables=[
            Variable(name="x", lower_bound=0, upper_bound=4),
            Variable(name="y", lower_bound=0),
        ],
        objective=Objective(
            sense=sense,
            expression="3*x + 2*y" if sense is ObjectiveSense.MAXIMIZE else "-3*x - 2*y",
        ),
        constraints=[
            Constraint(name="capacity", expression="x + y <= 6"),
            Constraint(name="mix", expression="x - y <= 1"),
            Constraint(name="loose", expression="y <= 100"),
        ],
    )


def _knapsack(n: int = 40, **options) -> OptimizationProblem:
    generator = random.Random(7)
    weights = [generator.randint(10, 60) for _ in range(n)]
    values = [generator.randint(10, 60) for _ in range(n)]
    return OptimizationProblem(
        variables=[Variable(name=f"b{j}", type=VariableType.BINARY) for j in range(n)],
        objective=Objective(
            sense=ObjectiveSense.MAXIMIZE,
            expression=" + ".join(f"{values[j]}*b{j}" for j in range(n)),
        ),
        constraints=[
            Constraint(
                name="weight",
                expression=" + ".join(f"{weights[j]}*b{j}" for j in range(n))
                + f" <= {sum(weights) // 2}",
            )
        ],
        options=SolverOptions(gap_tolerance=0.0, **options),
    )


def test_capabilities_say_what_the_adapter_does() -> None:
    caps = JAOSAdapter.capabilities
    assert caps.name == "jaos"
    assert caps.supports_continuous and caps.supports_integer and caps.supports_binary
    assert caps.supports_sensitivity and caps.supports_warm_start and caps.supports_progress
    assert caps.supports_quadratic is False
    assert caps.supports_multi_objective is False


def test_the_library_is_available_and_reports_its_build() -> None:
    adapter = JAOSAdapter()
    assert adapter.is_available() is True
    # "0.5.0+g327f7e5d0a1b": two builds between tags share the version, so the
    # commit is part of what a stored comparison records.
    assert re.fullmatch(r"\d+\.\d+\.\d+(\+g[0-9a-f]+)?", adapter.version() or "")


def test_a_missing_library_is_unavailable_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    # None in sys.modules makes `import jaos` raise ImportError, which is what
    # jaos.LibraryNotFound (a subclass) does when libjaos.so cannot load.
    monkeypatch.setitem(sys.modules, "jaos", None)
    assert JAOSAdapter().is_available() is False


@pytest.mark.parametrize("sense", [ObjectiveSense.MAXIMIZE, ObjectiveSense.MINIMIZE])
def test_lp_prices_match_highs(sense: ObjectiveSense) -> None:
    problem = _lp(sense)
    jaos_result = JAOSAdapter().solve(problem)
    highs_result = HiGHSAdapter().solve(problem)

    assert jaos_result.status is SolverStatus.OPTIMAL
    assert jaos_result.objective_value == pytest.approx(highs_result.objective_value)
    assert jaos_result.gap == 0.0
    assert jaos_result.dual_bound == jaos_result.objective_value

    ours, theirs = jaos_result.sensitivity, highs_result.sensitivity
    assert ours is not None and theirs is not None
    assert ours.is_approximate is False
    assert [c.name for c in ours.constraints] == ["capacity", "mix", "loose"]
    for mine, reference in zip(ours.constraints, theirs.constraints, strict=True):
        assert mine.shadow_price == pytest.approx(reference.shadow_price, abs=1e-9)
        assert mine.is_binding == reference.is_binding
    assert [c.is_binding for c in ours.constraints] == [True, True, False]
    for mine, reference in zip(ours.variables, theirs.variables, strict=True):
        assert mine.reduced_cost == pytest.approx(reference.reduced_cost, abs=1e-9)
        assert mine.is_at_bound == reference.is_at_bound


def test_a_strict_inequality_on_its_limit_is_binding() -> None:
    problem = OptimizationProblem(
        variables=[Variable(name="x", lower_bound=0), Variable(name="y", lower_bound=0)],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + y"),
        constraints=[Constraint(name="strict", expression="x + y < 4")],
    )
    result = JAOSAdapter().solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.sensitivity is not None
    assert result.sensitivity.constraints[0].is_binding is True


def test_a_mip_reports_its_tree_and_no_prices() -> None:
    result = JAOSAdapter().solve(_knapsack())
    assert result.status is SolverStatus.OPTIMAL
    assert result.nodes is not None and result.nodes >= 1
    assert result.iterations is not None and result.iterations > 0
    # At a proven optimum JAOS reports the bound and the objective as one number.
    assert result.dual_bound == result.objective_value
    assert result.gap == 0.0
    # A MIP's duals belong to the last node, not to the answer.
    assert result.sensitivity is None
    assert all(value in (0.0, 1.0) for value in result.solution.values())


def test_infeasible_is_infeasible() -> None:
    problem = OptimizationProblem(
        variables=[Variable(name="x", lower_bound=0, upper_bound=1)],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x"),
        constraints=[Constraint(name="impossible", expression="x >= 5")],
    )
    result = JAOSAdapter().solve(problem)
    assert result.status is SolverStatus.INFEASIBLE
    assert result.objective_value is None
    assert not result.solution


def test_a_quadratic_model_is_refused_not_linearised() -> None:
    problem = OptimizationProblem(
        variables=[Variable(name="x", lower_bound=0, upper_bound=3)],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x*x - 2*x"),
        constraints=[Constraint(name="r", expression="x <= 3")],
    )
    result = JAOSAdapter().solve(problem)
    assert result.status is SolverStatus.ERROR
    assert "quadratic" in (result.error_message or "")


def test_threads_zero_means_auto_and_solves() -> None:
    result = JAOSAdapter().solve(_knapsack(threads=0))
    assert result.status is SolverStatus.OPTIMAL


class TestMipStart:
    def test_a_partial_start_is_completed_and_reported_used(self) -> None:
        result = JAOSAdapter().solve(_knapsack(), warm_start={"b0": 1.0, "b1": 0.0})
        assert result.status is SolverStatus.OPTIMAL
        assert result.warm_start_used is True

    def test_an_infeasible_start_is_reported_unused(self) -> None:
        # Every item in: far over the weight limit, so JAOS drops the start.
        start = {f"b{j}": 1.0 for j in range(40)}
        result = JAOSAdapter().solve(_knapsack(), warm_start=start)
        assert result.status is SolverStatus.OPTIMAL
        assert result.warm_start_used is False

    def test_the_problem_heuristic_start_is_used_when_none_is_passed(self) -> None:
        problem = _knapsack()
        problem.heuristic_warm_start = {"b0": 1.0}
        result = JAOSAdapter().solve(problem)
        assert result.warm_start_used is True

    def test_an_lp_ignores_a_start(self) -> None:
        result = JAOSAdapter().solve(_lp(ObjectiveSense.MAXIMIZE), warm_start={"x": 1.0})
        assert result.status is SolverStatus.OPTIMAL
        assert result.warm_start_used is False

    def test_names_the_model_does_not_have_are_skipped(self) -> None:
        result = JAOSAdapter().solve(_knapsack(), warm_start={"ghost": 1.0})
        assert result.status is SolverStatus.OPTIMAL
        assert result.warm_start_used is False


class TestProgress:
    def test_points_stream_and_the_trace_ends_on_the_answer(self) -> None:
        streamed: list[ProgressPoint] = []
        result = JAOSAdapter().solve(_knapsack(), on_progress=streamed.append)

        assert result.status is SolverStatus.OPTIMAL
        assert streamed, "a MIP with an incumbent must stream at least one point"
        history = result.progress_history
        assert history is not None
        # Everything streamed is in the history, in order; the history may end
        # with one more point, at the answer.
        assert history[: len(streamed)] == streamed
        assert [p.iteration for p in history] == list(range(1, len(history) + 1))
        nodes = [p.node for p in history]
        assert nodes == sorted(nodes)
        elapsed = [p.elapsed_seconds for p in history]
        assert elapsed == sorted(elapsed)
        last = history[-1]
        assert last.objective == result.objective_value
        assert last.dual_bound == result.dual_bound
        assert last.node == result.nodes
        for point in history:
            assert point.primal_bound == point.objective

    def test_a_failing_consumer_does_not_stop_the_solve(self) -> None:
        calls = 0

        def broken(_point: ProgressPoint) -> None:
            nonlocal calls
            calls += 1
            raise RuntimeError("websocket down")

        result = JAOSAdapter().solve(_knapsack(), on_progress=broken)
        assert calls >= 1
        assert result.status is SolverStatus.OPTIMAL
        assert result.progress_history

    def test_an_lp_has_only_the_closing_point(self) -> None:
        result = JAOSAdapter().solve(_lp(ObjectiveSense.MAXIMIZE))
        assert result.progress_history is not None
        assert len(result.progress_history) == 1
        assert result.progress_history[0].objective == result.objective_value

    def test_a_long_search_keeps_reporting(self) -> None:
        """A point at least every 2 s, so the node count on the page keeps moving.

        On a search where neither the incumbent nor the bound moved, the panel
        showed 217 nodes for 16 seconds while JAOS had reached 21,527.
        """
        problem = _market_split(time_limit_seconds=6, with_slack=True)
        streamed: list[ProgressPoint] = []
        result = JAOSAdapter().solve(problem, on_progress=streamed.append)
        assert result.status is SolverStatus.TIME_LIMIT
        assert len(streamed) >= 3
        times = [p.elapsed_seconds for p in streamed]
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        assert max(gaps) <= 2.6, f"a {max(gaps)} s silence between points"
        assert streamed[-1].node > streamed[0].node

    def test_no_answer_means_no_trace(self) -> None:
        problem = OptimizationProblem(
            variables=[Variable(name="x", lower_bound=0, upper_bound=1)],
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x"),
            constraints=[Constraint(name="impossible", expression="x >= 5")],
        )
        assert JAOSAdapter().solve(problem).progress_history is None


def test_verbose_sends_the_solver_log_to_the_logger(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.domains.solver.adapters.jaos"):
        JAOSAdapter().solve(_knapsack(n=20, verbose=True))
    assert any(record.getMessage().startswith("JAOS: ") for record in caplog.records)


def test_silent_unless_verbose(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.domains.solver.adapters.jaos"):
        JAOSAdapter().solve(_knapsack(n=20))
    assert not any(record.getMessage().startswith("JAOS: ") for record in caplog.records)


def _market_split(time_limit_seconds: float = 30, with_slack: bool = False) -> OptimizationProblem:
    """Equality rows over binaries. Without slack there is no feasible point and JAOS
    searches until stopped; with slack it finds a point at once and cannot prove it."""
    generator = random.Random(7)
    width = 40
    variables = [Variable(name=f"b{j}", type=VariableType.BINARY) for j in range(width)]
    constraints = []
    objective = "b0"
    for i in range(5):
        row = [generator.randint(0, 99) for _ in range(width)]
        lhs = " + ".join(f"{row[j]}*b{j}" for j in range(width))
        if with_slack:
            lhs += f" + sp{i} - sm{i}"
            variables += [
                Variable(name=f"sp{i}", lower_bound=0),
                Variable(name=f"sm{i}", lower_bound=0),
            ]
        constraints.append(Constraint(name=f"r{i}", expression=f"{lhs} == {sum(row) // 2}"))
    if with_slack:
        objective = " + ".join(f"sp{i} + sm{i}" for i in range(5))
    return OptimizationProblem(
        variables=variables,
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression=objective),
        constraints=constraints,
        options=SolverOptions(time_limit_seconds=time_limit_seconds, gap_tolerance=0.0),
    )


class _SoftLimit(Exception):
    """Stands in for Celery's SoftTimeLimitExceeded, an Exception subclass."""


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="needs POSIX interval timers")
def test_an_exception_from_a_signal_handler_stops_the_solve_and_is_raised() -> None:
    """The worker's soft time limit arrives as a signal while JAOS runs in C.

    JAOS stops the solve and raises the handler's exception from ``solve()``.
    The adapter must pass it on: turning it into an ERROR result would hide
    what stopped the run, and swallowing it would let the solve run on to its
    own limit.
    """

    def raise_soft_limit(_signum, _frame) -> None:
        raise _SoftLimit

    problem = _market_split()
    previous = signal.signal(signal.SIGALRM, raise_soft_limit)
    started = time.monotonic()
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.3)
        with pytest.raises(_SoftLimit):
            JAOSAdapter().solve(problem)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    assert time.monotonic() - started < 5
