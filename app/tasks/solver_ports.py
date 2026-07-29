"""JAOT's side of the solver domain's host ports (D-16).

The domain declares what it needs in ``app.domains.solver.ports``; this module
answers with the platform's services. Importing it performs the registration,
and BOTH processes that run domain code import it at boot:

- the API — ``app.main`` calls :func:`register_solver_ports` in the lifespan;
- every Celery worker — this module sits on the Celery app's ``include`` list,
  so the worker imports it exactly like a task module before taking work.

Registration is import-driven and free of I/O on purpose: it must succeed
before any database or broker is reachable.
"""

from typing import Any

from app.domains.solver import ports
from app.domains.solver.services.scenario_analysis import ScenarioBudget
from app.services.marketplace_fusion import record_listing_execution
from app.services.notification_service import NotificationService
from app.services.platform_settings_service import PlatformSettingsService as PSS


def _read_scenario_budget(db: Any) -> ScenarioBudget:
    return ScenarioBudget(
        max_resolves=PSS.get_int(db, "SENSITIVITY_MAX_RESOLVES"),
        top_constraints=PSS.get_int(db, "SENSITIVITY_TOP_CONSTRAINTS"),
        top_decisions=PSS.get_int(db, "SENSITIVITY_TOP_DECISIONS"),
        per_solve_multiplier=PSS.get_float(db, "SENSITIVITY_PER_SOLVE_MULTIPLIER"),
        per_solve_cap_seconds=PSS.get_int(db, "SENSITIVITY_PER_SOLVE_CAP_SECONDS"),
        total_seconds=PSS.get_int(db, "SENSITIVITY_TOTAL_BUDGET_SECONDS"),
    )


class PlatformSolveEvents:
    """Marketplace statistics and the notification bell, as one sink."""

    def listing_executed(
        self,
        db: Any,
        listing_id: str,
        *,
        succeeded: bool,
        execution_time_ms: float | None,
    ) -> None:
        record_listing_execution(
            db, listing_id, succeeded=succeeded, execution_time_ms=execution_time_ms
        )

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
        NotificationService(db).notify_execution_completed(
            user_id=user_id,
            organization_id=organization_id,
            execution_id=execution_id,
            model_name=model_name,
            objective_value=objective_value,
        )

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
        NotificationService(db).notify_execution_failed(
            user_id=user_id,
            organization_id=organization_id,
            execution_id=execution_id,
            model_name=model_name,
            error=error,
        )


def register_solver_ports() -> None:
    """Idempotent; safe to call from more than one entry point."""
    ports.register_scenario_budget_reader(_read_scenario_budget)
    ports.register_solve_event_sink(PlatformSolveEvents())


# Importing this module IS the registration: the Celery ``include`` list can
# import a module at worker boot but cannot call a function in it.
register_solver_ports()
