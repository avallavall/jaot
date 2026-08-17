"""The reaper must not kill a comparison column that is only waiting its turn.

A comparison writes one execution per solver and solves them one at a time on a
worker that runs one comparison at a time. A column can therefore sit 'pending'
far longer than any ordinary queued solve, and judged by its own age it looks
exactly like the lost task the reaper exists to clean up.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import ExecutionStatus, ModelExecution, Organization, SolverComparison
from app.models.solver_comparison import ComparisonStatus
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from app.tasks.execution_reaper import reap_stale_executions

# Seeded by the _seed_platform_settings autouse fixture.
PENDING_MAX = 1800


@pytest.fixture
def comparison_org(db_session):
    org = Organization(id=generate_id("org_"), name="Comparison Reaper Org", is_active=True)
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


def _seed(
    db_session,
    org,
    *,
    parent_age_seconds: int,
    parent_status: str = ComparisonStatus.RUNNING.value,
    time_limit_seconds: float = 60.0,
    solver_names: list[str] | None = None,
    batch_id: str | None = None,
    batch_rows: int = 1,
) -> tuple[SolverComparison, ModelExecution]:
    """A comparison plus one column of it, still pending."""
    names = solver_names or ["scip", "highs"]
    created = utcnow() - timedelta(seconds=parent_age_seconds)
    comparison = SolverComparison(
        id=generate_id("cmp_"),
        organization_id=org.id,
        problem_data={"name": "reaper-comparison"},
        problem_name="reaper-comparison",
        time_limit_seconds=time_limit_seconds,
        gap_tolerance=0.0001,
        threads=1,
        solver_names=names,
        status=parent_status,
        created_at=created,
        started_at=created,
        batch_id=batch_id,
        batch_position=0,
    )
    db_session.add(comparison)
    # The siblings this row waits behind. Only their existence matters to the
    # reaper: they are what makes the row's honest bound the whole matrix.
    for position in range(1, batch_rows):
        db_session.add(
            SolverComparison(
                id=generate_id("cmp_"),
                organization_id=org.id,
                problem_data=None,
                time_limit_seconds=time_limit_seconds,
                gap_tolerance=0.0001,
                threads=1,
                solver_names=names,
                status=ComparisonStatus.PENDING.value,
                created_at=created,
                batch_id=batch_id,
                batch_position=position,
            )
        )
    db_session.flush()

    execution = ModelExecution(
        id=generate_id("exe_"),
        organization_id=org.id,
        comparison_id=comparison.id,
        celery_task_id=None,
        is_async=True,
        status=ExecutionStatus.PENDING.value,
        input_data={"name": "reaper-comparison"},
        created_at=created,
        solver_name=names[-1],
        origin="comparison",
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)
    return comparison, execution


# CONTRACT-TEST: a column waiting its turn inside a live comparison is never
# reaped. Reaping it would mark a good run failed while its solver was still
# queued behind the others.
def test_a_column_of_a_live_comparison_is_not_reaped(db_session, comparison_org) -> None:
    # Older than the pending threshold, which is exactly the trap: an ordinary
    # queued solve this old would be reaped.
    _comparison, execution = _seed(db_session, comparison_org, parent_age_seconds=PENDING_MAX + 600)

    reap_stale_executions(db_session)

    db_session.refresh(execution)
    assert execution.status == ExecutionStatus.PENDING.value
    assert execution.error_message is None


# CONTRACT-TEST: the protection is bounded. A comparison stuck past its own time
# budget is genuinely dead and its columns must not stay pending forever.
def test_a_column_of_a_comparison_past_its_budget_is_reaped(db_session, comparison_org) -> None:
    # Budget is (solvers x time limit) + running_max slack, so age it well past
    # the running threshold too.
    _comparison, execution = _seed(
        db_session,
        comparison_org,
        parent_age_seconds=400_000,
        time_limit_seconds=60.0,
    )

    reap_stale_executions(db_session)

    db_session.refresh(execution)
    assert execution.status == ExecutionStatus.FAILED.value
    assert execution.error_message


# CONTRACT-TEST: once the parent reaches a verdict, its columns lose the
# protection — a column left pending under a finished comparison is a real leak.
def test_a_column_of_a_finished_comparison_is_reaped(db_session, comparison_org) -> None:
    _comparison, execution = _seed(
        db_session,
        comparison_org,
        parent_age_seconds=PENDING_MAX + 600,
        parent_status=ComparisonStatus.COMPLETED.value,
    )

    reap_stale_executions(db_session)

    db_session.refresh(execution)
    assert execution.status == ExecutionStatus.FAILED.value


def test_an_ordinary_solve_is_still_reaped(db_session, comparison_org) -> None:
    """The comparison carve-out must not weaken the sweep for everything else."""
    execution = ModelExecution(
        id=generate_id("exe_"),
        organization_id=comparison_org.id,
        celery_task_id=f"task_{generate_id('exe_')}",
        is_async=True,
        status=ExecutionStatus.PENDING.value,
        input_data={"name": "ordinary"},
        created_at=utcnow() - timedelta(seconds=PENDING_MAX + 600),
        solver_name="scip",
    )
    db_session.add(execution)
    db_session.commit()

    reap_stale_executions(db_session)

    db_session.refresh(execution)
    assert execution.status == ExecutionStatus.FAILED.value


# CONTRACT-TEST: a row of a MATRIX waits for every row before it, so its bound is
# the whole matrix and not its own four solves. Judged by its own budget, the
# last row of a twelve-row matrix looks abandoned for most of the run and the
# reaper would mark it failed while it sat legitimately in the queue.
def test_a_column_of_a_matrix_waits_for_the_whole_matrix(db_session, comparison_org) -> None:
    # Well past ONE row's budget (2 solvers x 60 s + slack) and well inside the
    # matrix's (12 rows x that).
    _comparison, execution = _seed(
        db_session,
        comparison_org,
        parent_age_seconds=PENDING_MAX + 600,
        time_limit_seconds=60.0,
        batch_id="cmb_reaper",
        batch_rows=12,
    )

    reap_stale_executions(db_session)

    db_session.refresh(execution)
    assert execution.status == ExecutionStatus.PENDING.value
    assert execution.error_message is None


# CONTRACT-TEST: the wider bound is still a bound. A matrix past even its own
# total budget is genuinely stuck and its columns must not stay pending forever.
def test_a_column_of_a_matrix_past_the_whole_budget_is_reaped(db_session, comparison_org) -> None:
    _comparison, execution = _seed(
        db_session,
        comparison_org,
        parent_age_seconds=400_000,
        time_limit_seconds=60.0,
        batch_id="cmb_reaper_dead",
        batch_rows=12,
    )

    reap_stale_executions(db_session)

    db_session.refresh(execution)
    assert execution.status == ExecutionStatus.FAILED.value
    assert execution.error_message
