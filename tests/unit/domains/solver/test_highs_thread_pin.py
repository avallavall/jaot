"""HiGHS keeps one task scheduler per process, and its size cannot change.

Found on 2026-08-14 while building the solver comparer. HiGHS starts a task
scheduler on the first solve in a process, sized by the thread count in force at
that moment. Asking a later ``Highs()`` for a different count does not resize
it: ``setOptionValue`` returns kOk, then the solve reports model status
"Not Set", which the adapter maps to ERROR. No exception and no message — the
column just says "error".

That hit production code, not only tests: the HiGHS worker is long-lived, so the
first solve to name a thread count decided it for every solve after it, and any
later solve naming a different one failed silently.
"""

from __future__ import annotations

import pytest

from app.domains.solver.adapters import highs as highs_mod
from app.domains.solver.adapters.highs import HiGHSAdapter
from app.schemas.optimization import (
    Constraint,
    Objective,
    OptimizationProblem,
    SolverOptions,
    SolverStatus,
    Variable,
    VariableType,
)


def _problem(threads: int) -> OptimizationProblem:
    return OptimizationProblem(
        name="thread-pin",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0.0),
        ],
        constraints=[Constraint(expression="x + y <= 10")],
        objective=Objective(expression="3*x + 2*y", sense="maximize"),
        options=SolverOptions(time_limit_seconds=30.0, verbose=False, threads=threads),
    )


class TestPinProcessThreads:
    """The pin itself, without touching the library."""

    def test_the_first_request_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(highs_mod, "_process_threads", None)
        assert highs_mod._pin_process_threads(4) == 4
        assert highs_mod._pin_process_threads(4) == 4

    def test_a_later_different_request_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(highs_mod, "_process_threads", None)
        highs_mod._pin_process_threads(4)
        # Honouring it would make the solve fail silently, which is worse than
        # running on a thread count the caller did not ask for.
        assert highs_mod._pin_process_threads(1) == 4

    def test_auto_is_a_pin_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A process whose first solve let HiGHS choose has a scheduler as much as
        # one that named a number, so a later explicit count is just as refused.
        monkeypatch.setattr(highs_mod, "_process_threads", None)
        assert highs_mod._pin_process_threads(0) == 0
        assert highs_mod._pin_process_threads(2) == 0


# CONTRACT-TEST: two HiGHS solves in one process with DIFFERENT requested thread
# counts must both produce a real answer. This is the regression lock on the
# silent "Not Set" failure — it fails against the pre-pin adapter.
def test_two_solves_with_different_thread_requests_both_succeed() -> None:
    adapter = HiGHSAdapter()

    first = adapter.solve(_problem(threads=1))
    second = adapter.solve(_problem(threads=7))

    assert first.status == SolverStatus.OPTIMAL, first.error_message
    assert second.status == SolverStatus.OPTIMAL, second.error_message
    assert first.objective_value == pytest.approx(30.0)
    assert second.objective_value == pytest.approx(30.0)
