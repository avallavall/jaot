"""The contracts the solver domain needs its host to fulfil (D-16).

This bounded context is written to be extractable: the direction test for every
import is *could this code run outside JAOT?*. A solve's outcome concerns the
host (a marketplace listing to bump, a user to notify), and the what-if budget
is platform configuration — so instead of importing the platform services that
implement them, the domain declares the two ports here and the host registers
implementations at boot.

JAOT registers in BOTH processes that execute domain code:

- the API process — ``app.main`` imports ``app.tasks.solver_ports`` and calls
  its registration in the lifespan (the producer side reads the scenario
  budget to derive Celery kill limits);
- every Celery worker — ``app.tasks.solver_ports`` sits on the Celery app's
  ``include`` list next to the task modules, so a worker cannot come up
  without importing it.

There is deliberately NO default implementation: an unregistered port raises
instead of falling back, because the silent alternative — a batch computed
with the wrong budget, a notification that never leaves — is invisible to a
test suite that runs both processes as one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.domains.solver.services.scenario_analysis import ScenarioBudget

# Takes the caller's DB session (opaque to the domain) so the host's reads and
# writes share the task's transaction.
ScenarioBudgetReader = Callable[[Any], ScenarioBudget]


class SolveEventSink(Protocol):
    """Where the domain hands a solve's outcome, without knowing who listens."""

    def listing_executed(
        self,
        db: Any,
        listing_id: str,
        *,
        succeeded: bool,
        execution_time_ms: float | None,
    ) -> None:
        """A run attributable to a listing reached a terminal state."""

    def solve_completed(
        self,
        db: Any,
        *,
        user_id: str,
        organization_id: str,
        execution_id: str,
        model_name: str,
        objective_value: float | None,
    ) -> None:
        """A model execution finished with a solution."""

    def solve_failed(
        self,
        db: Any,
        *,
        user_id: str,
        organization_id: str,
        execution_id: str,
        model_name: str,
        error: str,
    ) -> None:
        """A model execution ended in failure (or was cancelled by its user)."""


_scenario_budget_reader: ScenarioBudgetReader | None = None
_solve_event_sink: SolveEventSink | None = None


def register_scenario_budget_reader(reader: ScenarioBudgetReader) -> None:
    global _scenario_budget_reader
    _scenario_budget_reader = reader


def register_solve_event_sink(sink: SolveEventSink) -> None:
    global _solve_event_sink
    _solve_event_sink = sink


def scenario_budget(db: Any) -> ScenarioBudget:
    """The what-if batch budget, read through the host's settings.

    Read at the producer AND the consumer: the API needs the total to derive
    the task's kill limits, the worker needs the whole shape. Reading it twice
    is cheaper than threading a settings blob through the queue, and an admin
    edit between the two only changes the batch's own ceiling.
    """
    if _scenario_budget_reader is None:
        raise RuntimeError(_unregistered("scenario-budget reader"))
    return _scenario_budget_reader(db)


def solve_events() -> SolveEventSink:
    """The host's listeners for solve outcomes."""
    if _solve_event_sink is None:
        raise RuntimeError(_unregistered("solve-event sink"))
    return _solve_event_sink


def _unregistered(port: str) -> str:
    return (
        f"No {port} registered. The host must wire the solver domain's ports at "
        "boot — JAOT does this in app.tasks.solver_ports, imported by app.main "
        "(API) and by the Celery include list (workers). This raises instead of "
        "falling back on purpose: the silent alternative is a wrong budget or a "
        "lost notification."
    )
