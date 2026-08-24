"""Cross-execution analytics for optimization results.

Aggregation, trend analysis, and side-by-side comparison
across an organization's execution history.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Any, Literal

from sqlalchemy.orm import Session, selectinload

from app.models import ModelExecution
from app.shared.utils.datetime_helpers import utcnow

BucketSize = Literal["day", "week"]

# Hard cap for "all time" queries to prevent unbounded table scans.
_MAX_LOOKBACK_DAYS = 365


@dataclass(frozen=True)
class AnalyticsSummary:
    """Aggregated stats for an org's executions within a time window."""

    total_executions: int
    completed: int
    failed: int
    timed_out: int
    success_rate: float
    avg_solve_time_ms: float | None
    median_solve_time_ms: float | None
    avg_objective_value: float | None
    executions_by_status: Mapping[str, int]
    executions_by_origin: Mapping[str, int]
    solver_status_distribution: Mapping[str, int]


@dataclass(frozen=True)
class TrendBucket:
    """A single time-bucket in a trend series."""

    date: str  # ISO date string (YYYY-MM-DD)
    executions: int
    completed: int
    failed: int
    avg_solve_time_ms: float | None


@dataclass(frozen=True)
class ComparedExecution:
    """A single execution in a comparison set."""

    id: str
    status: str
    solver_status: str | None
    objective_value: float | None
    execution_time_ms: int | None
    created_at: str
    origin: str
    num_variables: int | None
    num_constraints: int | None
    gap: float | None


def _base_query(db: Session, org_id: str, days: int):
    """Build the org-scoped, time-bounded query over the analytics columns ONLY.

    Selecting whole ``ModelExecution`` rows is what made these endpoints take
    7-16 seconds over a 650-row window: the table carries each run's problem and
    solution JSON — 96 MB across 870 rows on the reference install — so counting
    statuses dragged every model and every solution over the wire and built a
    Python object for each. The aggregates read six columns; this selects six.
    """
    effective_days = min(days, _MAX_LOOKBACK_DAYS) if days > 0 else _MAX_LOOKBACK_DAYS
    cutoff = utcnow() - timedelta(days=effective_days)
    return db.query(
        ModelExecution.created_at,
        ModelExecution.status,
        ModelExecution.origin,
        ModelExecution.solver_status,
        ModelExecution.execution_time_ms,
        ModelExecution.objective_value,
    ).filter(
        ModelExecution.organization_id == org_id,
        ModelExecution.created_at >= cutoff,
    )


def compute_summary(db: Session, org_id: str, days: int) -> AnalyticsSummary:
    """Compute aggregated analytics for an organization.

    Args:
        db: Database session.
        org_id: Organization ID for multi-tenant filtering.
        days: Look-back window in days (0 = all time, capped at 365).
    """
    query = _base_query(db, org_id, days)

    executions = query.all()

    if not executions:
        return AnalyticsSummary(
            total_executions=0,
            completed=0,
            failed=0,
            timed_out=0,
            success_rate=0.0,
            avg_solve_time_ms=None,
            median_solve_time_ms=None,
            avg_objective_value=None,
            executions_by_status={},
            executions_by_origin={},
            solver_status_distribution={},
        )

    total = len(executions)
    status_counts: dict[str, int] = {}
    origin_counts: dict[str, int] = {}
    solver_status_counts: dict[str, int] = {}
    solve_times: list[int] = []
    objectives: list[float] = []

    for exe in executions:
        status_counts[exe.status] = status_counts.get(exe.status, 0) + 1
        origin_counts[exe.origin] = origin_counts.get(exe.origin, 0) + 1
        if exe.solver_status:
            solver_status_counts[exe.solver_status] = (
                solver_status_counts.get(exe.solver_status, 0) + 1
            )
        if exe.execution_time_ms is not None:
            solve_times.append(exe.execution_time_ms)
        if exe.objective_value is not None:
            objectives.append(exe.objective_value)

    completed = status_counts.get("completed", 0)
    failed = status_counts.get("failed", 0)
    timed_out = status_counts.get("timeout", 0)

    median_time: float | None = None
    if solve_times:
        sorted_times = sorted(solve_times)
        mid = len(sorted_times) // 2
        median_time = (
            float(sorted_times[mid])
            if len(sorted_times) % 2
            else (sorted_times[mid - 1] + sorted_times[mid]) / 2.0
        )

    return AnalyticsSummary(
        total_executions=total,
        completed=completed,
        failed=failed,
        timed_out=timed_out,
        success_rate=completed / total if total else 0.0,
        avg_solve_time_ms=sum(solve_times) / len(solve_times) if solve_times else None,
        median_solve_time_ms=median_time,
        avg_objective_value=sum(objectives) / len(objectives) if objectives else None,
        executions_by_status=MappingProxyType(status_counts),
        executions_by_origin=MappingProxyType(origin_counts),
        solver_status_distribution=MappingProxyType(solver_status_counts),
    )


def compute_trends(
    db: Session,
    org_id: str,
    days: int,
    bucket: BucketSize = "day",
) -> list[TrendBucket]:
    """Compute time-series trend data bucketed by day or week.

    Args:
        db: Database session.
        org_id: Organization ID.
        days: Look-back window in days (0 = all time, capped at 365).
        bucket: Aggregation bucket size.
    """
    query = _base_query(db, org_id, days)
    executions = query.order_by(ModelExecution.created_at.asc()).all()

    if not executions:
        return []

    # Group into buckets. The rows are column tuples, not ModelExecution
    # instances — see _base_query for why.
    buckets: dict[str, list[Any]] = {}
    for exe in executions:
        if bucket == "week":
            # ISO week start (Monday)
            dt = exe.created_at
            week_start = dt - timedelta(days=dt.weekday())
            key = week_start.strftime("%Y-%m-%d")
        else:
            key = exe.created_at.strftime("%Y-%m-%d")
        buckets.setdefault(key, []).append(exe)

    result: list[TrendBucket] = []
    for date_key in sorted(buckets):
        group = buckets[date_key]
        times = [e.execution_time_ms for e in group if e.execution_time_ms is not None]
        result.append(
            TrendBucket(
                date=date_key,
                executions=len(group),
                completed=sum(1 for e in group if e.status == "completed"),
                failed=sum(1 for e in group if e.status == "failed"),
                avg_solve_time_ms=sum(times) / len(times) if times else None,
            )
        )

    return result


def compare_executions(
    db: Session,
    org_id: str,
    execution_ids: list[str],
) -> list[ComparedExecution]:
    """Load and normalize executions for side-by-side comparison.

    Args:
        db: Database session.
        org_id: Organization ID for access control.
        execution_ids: List of execution IDs to compare (max 10).

    Returns:
        List of ComparedExecution in the same order as execution_ids.
        Missing/inaccessible IDs are silently skipped.
    """
    rows = (
        db.query(ModelExecution)
        # A column of a comparison holds no problem of its own and would read it
        # off its parent one row at a time. Only the two sizes below are wanted,
        # and the parent already stores them as integers — so the parent is
        # loaded once for the whole batch and the snapshot is never touched.
        .options(selectinload(ModelExecution.comparison))
        .filter(
            ModelExecution.id.in_(execution_ids),
            ModelExecution.organization_id == org_id,
        )
        .all()
    )

    by_id = {r.id: r for r in rows}
    result: list[ComparedExecution] = []

    for eid in execution_ids:
        exe = by_id.get(eid)
        if not exe:
            continue

        # Problem size. A comparison records both as integers when it snapshots
        # the problem, so a column of one is answered without reading a 3.8 MB
        # blob to call len() on two of its keys.
        if exe.comparison is not None:
            num_vars = exe.comparison.variable_count
            num_cons = exe.comparison.constraint_count
        else:
            variables = exe.input_data.get("variables") if exe.input_data else None
            constraints = exe.input_data.get("constraints") if exe.input_data else None
            num_vars = len(variables) if isinstance(variables, list) else None
            num_cons = len(constraints) if isinstance(constraints, list) else None

        # Extract gap from result_data (safely handle non-numeric values)
        result_data = exe.result_data or {}
        raw_gap = result_data.get("gap")
        try:
            gap = float(raw_gap) if raw_gap is not None else None
        except (TypeError, ValueError):
            gap = None

        result.append(
            ComparedExecution(
                id=exe.id,
                status=exe.status,
                solver_status=exe.solver_status,
                objective_value=exe.objective_value,
                execution_time_ms=exe.execution_time_ms,
                created_at=exe.created_at.isoformat(),
                origin=exe.origin,
                num_variables=num_vars,
                num_constraints=num_cons,
                gap=gap,
            )
        )

    return result
