"""Celery tasks for async processing."""

from app.domains.solver.tasks.solve_tasks import solve_async, solve_model_async

__all__ = ["solve_async", "solve_model_async"]
