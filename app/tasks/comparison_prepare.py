"""Compile one row of a solver matrix, then hand it to the comparison worker.

A matrix crosses N datasets with M solvers. Every dataset compiles to its own
problem, and on the models this platform is actually used for that problem is
several megabytes: measured at 3.8 MB for 22,500 variables, written once for the
row and once per cell. Doing all of it inside ``POST /solvers/compare/batches``
cost 28 seconds and 57 MB for three datasets, and would have passed a proxy's
100-second ceiling at twelve — the browser would report a failure for a matrix
that was running perfectly well.

So the launch writes the rows and nothing else, and one of these tasks per row
does the compiling. It runs on ``solve_compare``, the same single-slot queue the
solving uses, which orders the whole matrix for free: every row is enqueued for
preparation up front, so all the preparing happens before any solving starts.

**Why this task lives in app/tasks/ and not in the solver domain.** It needs the
JModel compiler, and a solver-domain module importing ``app.domains.dsl`` breaks
the import contract that keeps the domains independent. This module is outside
both, which is exactly what it is for.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.shared.core.celery_app import celery_app
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)


def _own_session() -> Any:
    """A session of this module's own, resolved at call time.

    Deliberately not bound at import: the test harness swaps ``SessionLocal`` on
    the session module, and an import-time binding keeps pointing at a database
    the suite never created.
    """
    from app.shared.db.session import SessionLocal  # noqa: PLC0415

    return SessionLocal()


@celery_app.task(bind=True, name="prepare_comparison_row")  # type: ignore[misc]
def prepare_comparison_row(
    self: Any,
    comparison_id: str,
    organization_id: str,
) -> dict[str, Any]:
    """Compile this row's dataset, write its cells, and queue the solving.

    A failure here is this row's failure and nobody else's. The other rows of the
    matrix carry different data and there is no reason one broken dataset should
    take them with it — and the row stays in the grid saying what went wrong,
    which is what a reader needs. It is a visible failure, not a missing row.
    """
    from app.models import ModelProject, ModelProjectDataset, SolverComparison  # noqa: PLC0415
    from app.models.solver_comparison import ComparisonStatus  # noqa: PLC0415

    logger.info("Preparing comparison row %s (task %s)", comparison_id, self.request.id)
    db = _own_session()
    try:
        comparison = (
            db.query(SolverComparison)
            .filter(
                SolverComparison.id == comparison_id,
                SolverComparison.organization_id == organization_id,
            )
            .first()
        )
        if comparison is None:
            raise ValueError(f"Comparison {comparison_id} not found")

        if comparison.status == ComparisonStatus.CANCELLED.value:
            logger.info("Row %s was cancelled before it was prepared", comparison_id)
            return {"status": "cancelled", "comparison_id": comparison_id}

        if comparison.problem_data is not None:
            # Already prepared by an earlier attempt of this task. Solving is
            # idempotent from here, so carry straight on to it.
            _queue_solving(db, comparison)
            return {"status": "already_prepared", "comparison_id": comparison_id}

        project = (
            db.query(ModelProject)
            .filter(
                ModelProject.id == comparison.model_project_id,
                ModelProject.organization_id == organization_id,
            )
            .first()
        )
        dataset = (
            db.query(ModelProjectDataset)
            .filter(
                ModelProjectDataset.id == comparison.dataset_id,
                ModelProjectDataset.organization_id == organization_id,
            )
            .first()
        )
        source = _source_of(db, project, comparison)
        if project is None or dataset is None or not source:
            # The model, the dataset or the source went away between the launch
            # and this row's turn. A matrix of twelve rows can take minutes, so
            # this is a real window, and the row says so rather than crashing.
            _fail(db, comparison, "The model or the dataset was deleted before this row ran.")
            return {"status": "error", "comparison_id": comparison_id, "error": "source_gone"}

        if not _compile_and_write(db, comparison, source, dataset):
            # The row already carries the reason it cannot run. Queueing it for
            # solving anyway would spend a slot on a row with no problem to
            # solve, and the solver task would overwrite that reason with a
            # validation error nobody can act on.
            return {"status": "error", "comparison_id": comparison_id, "error": "did_not_compile"}

        _queue_solving(db, comparison)
        return {"status": "success", "comparison_id": comparison_id}

    except HTTPException as exc:
        # The instance caps and the problem validator speak in HTTP terms because
        # they are shared with the request path. Here they are just a reason.
        detail = exc.detail
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        logger.warning("Row %s cannot be prepared: %s", comparison_id, message)
        _fail_by_id(db, comparison_id, organization_id, str(message))
        return {"status": "error", "comparison_id": comparison_id, "error": str(message)}
    except Exception as exc:
        logger.error("Row %s failed to prepare: %s", comparison_id, exc)
        _fail_by_id(db, comparison_id, organization_id, str(exc))
        return {"status": "error", "comparison_id": comparison_id, "error": str(exc)}
    finally:
        db.close()


def _source_of(db: Any, project: Any, comparison: Any) -> str | None:
    """The JModel source this row compiles: the pinned version's, or the draft."""
    if project is None:
        return None
    if not comparison.model_project_version_id:
        return project.draft_dsl_source

    from app.models.model_project import ModelProjectVersion  # noqa: PLC0415

    version = (
        db.query(ModelProjectVersion)
        .filter(
            ModelProjectVersion.id == comparison.model_project_version_id,
            ModelProjectVersion.model_project_id == project.id,
        )
        .first()
    )
    return version.dsl_source if version is not None else None


def _compile_and_write(db: Any, comparison: Any, source: str, dataset: Any) -> bool:
    """Compile the dataset against the source and write the row's cells.

    Everything the launch used to do per dataset happens here instead, for one
    dataset: compile, apply the instance caps, reject a malformed model once, and
    decide which solvers can express it.

    Returns whether the row is ready to be solved.
    """
    from app.domains.dsl import JModelData, JModelError, compile_jmodel  # noqa: PLC0415
    from app.domains.solver.services.classify import classify  # noqa: PLC0415
    from app.domains.solver.services.comparison_service import (  # noqa: PLC0415
        build_comparison_problem,
        plan_comparison,
    )
    from app.models import User  # noqa: PLC0415
    from app.services.solve_orchestrator import validate_problem  # noqa: PLC0415
    from app.services.solver_comparison_setup import (  # noqa: PLC0415
        enforce_instance_caps,
        insert_comparison_child,
    )

    try:
        problem = compile_jmodel(source, data=JModelData.from_json(dataset.data_json))
    except JModelError as exc:
        position = f" ({exc.position})" if exc.position else ""
        _fail(db, comparison, f"This dataset does not fill the model: {exc.message}{position}")
        return False

    problem = build_comparison_problem(
        problem,
        time_limit_seconds=comparison.time_limit_seconds,
        gap_tolerance=comparison.gap_tolerance,
        threads=comparison.threads,
    )
    problem = enforce_instance_caps(db, problem)
    validate_problem(problem)

    problem_class = classify(problem)
    plan = plan_comparison(problem, list(comparison.solver_names or []), problem_class)

    comparison.problem_data = problem.model_dump(mode="json")
    comparison.problem_class = problem_class.value
    comparison.variable_count = len(problem.variables)
    comparison.constraint_count = len(problem.constraints)
    # The plan can differ from what was asked for only in WHY a solver sits out,
    # never in who the columns are: the grid's shape was fixed at launch.
    comparison.solver_names = [entry.solver_name for entry in plan]
    db.flush()

    # The user who launched the matrix, so every cell records who ran it. Gone if
    # the account was deleted between the launch and this row's turn, which the
    # child writer has to tolerate rather than crash on.
    user = (
        db.query(User).filter(User.id == comparison.created_by_user_id).first()
        if comparison.created_by_user_id
        else None
    )
    provenance = {
        "source_kind": comparison.source_kind,
        "source_id": comparison.source_id,
        "model_project_id": comparison.model_project_id,
        "model_project_version_id": comparison.model_project_version_id,
    }
    for entry in plan:
        insert_comparison_child(db, comparison, entry, problem, provenance, user)
    db.commit()
    return True


def _queue_solving(db: Any, comparison: Any) -> None:
    """Hand the prepared row to the comparison worker.

    Onto the same single-slot queue this task is running on, so it lands behind
    every row still waiting to be prepared. That is the ordering worth having:
    the whole matrix is compiled and checked before the first solve starts.
    """
    from app.domains.solver.queue_routing import COMPARISON_QUEUE  # noqa: PLC0415
    from app.domains.solver.tasks.comparison_tasks import run_solver_comparison  # noqa: PLC0415

    task_id = str(uuid4())
    comparison.celery_task_id = task_id
    db.commit()
    run_solver_comparison.apply_async(
        kwargs={
            "comparison_id": comparison.id,
            "organization_id": comparison.organization_id,
        },
        task_id=task_id,
        queue=COMPARISON_QUEUE,
    )


def _fail(db: Any, comparison: Any, message: str) -> None:
    """Mark this row failed, with a sentence a reader can act on."""
    from app.models.solver_comparison import ComparisonStatus  # noqa: PLC0415

    comparison.status = ComparisonStatus.FAILED.value
    comparison.error_message = message[:2000]
    comparison.completed_at = utcnow()
    db.commit()


def _fail_by_id(db: Any, comparison_id: str, organization_id: str, message: str) -> None:
    """Best-effort terminal write so a row never stays pending for ever."""
    from app.models import SolverComparison  # noqa: PLC0415

    try:
        db.rollback()
        comparison = (
            db.query(SolverComparison)
            .filter(
                SolverComparison.id == comparison_id,
                SolverComparison.organization_id == organization_id,
            )
            .first()
        )
        if comparison is not None:
            _fail(db, comparison, message)
    except Exception as exc:  # pragma: no cover - the failure path's own failure
        logger.warning("Could not record the failure of row %s: %s", comparison_id, exc)
