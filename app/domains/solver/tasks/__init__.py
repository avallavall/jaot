"""Solver domain tasks — Celery async task definitions.

Phase 6.1 Plan 06 fix: register default solver adapters on package import.

Celery workers start with ``celery -A app.shared.core.celery_app worker
-Q solve_scip`` and ``celery_app.conf.include`` lists
``app.domains.solver.tasks.solve_tasks`` directly (see
``app/shared/core/celery_app.py``). Loading this package triggers the import
chain that registers the adapters BEFORE Celery dispatches any task, without
violating the ``shared-no-import-domains`` import-linter contract (the
registration lives inside the solver domain).

FastAPI also calls ``register_default_adapters()`` from
``app.main.create_app()`` during API startup. The function is idempotent
(last-write-wins per its docstring), so calling it both from the API and
from worker task import is safe.
"""

from app.domains.solver.adapters import register_default_adapters
from app.domains.solver.tasks.solve_tasks import solve_async, solve_model_async

register_default_adapters()

__all__ = ["solve_async", "solve_model_async"]
