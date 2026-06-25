"""Platform-wide analytics aggregations for the admin dashboard.

Unlike ``app/domains/solver/services/analytics.py`` (which is org-scoped and
loads rows into memory), these aggregations run across ALL organizations and
push the work into SQL (``COUNT``/``AVG``/``percentile_cont``/``GROUP BY``).
They are admin-only — every endpoint that calls them sits behind
``get_admin_user`` — so the usual per-org tenancy filter is intentionally
omitted: an admin sees the whole platform.

Three views, each accepting a ``days`` look-back window (0 = all time, capped
at 365 to bound table scans):

* ``compute_platform_overview`` — growth + usage + per-category breakdown
* ``compute_reliability``        — SLO percentiles, failures, automation health
* ``compute_ai_usage``           — LLM adoption, token/cost, acceptance, ratings
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models import (
    FormulationRating,
    LLMConversation,
    LLMMessage,
    ModelCatalog,
    ModelExecution,
    Organization,
    OrganizationModel,
    SolveTrigger,
    TriggerRun,
    TriggerSchedule,
    User,
)
from app.shared.utils.datetime_helpers import utcnow

# Hard cap for "all time" queries to prevent unbounded table scans.
_MAX_LOOKBACK_DAYS = 365

# Low-success model surfacing thresholds (reliability view).
_LOW_SUCCESS_THRESHOLD = 0.8
_LOW_SUCCESS_MIN_EXECUTIONS = 5

_PLAN_KEYS = ("free", "starter", "pro", "business")


def _cutoff(days: int):
    """Resolve the look-back cutoff datetime (0 = all time, capped at 365d)."""
    effective = min(days, _MAX_LOOKBACK_DAYS) if days > 0 else _MAX_LOOKBACK_DAYS
    return utcnow() - timedelta(days=effective)


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def compute_platform_overview(db: Session, days: int) -> dict[str, Any]:
    """Growth, usage, and per-category breakdown across the whole platform."""
    cutoff = _cutoff(days)

    # ── Business: users / orgs ────────────────────────────────────────────
    total_users = db.query(func.count(User.id)).scalar() or 0
    active_users = db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
    new_users = db.query(func.count(User.id)).filter(User.created_at >= cutoff).scalar() or 0
    total_orgs = db.query(func.count(Organization.id)).scalar() or 0
    active_orgs = (
        db.query(func.count(Organization.id)).filter(Organization.is_active.is_(True)).scalar() or 0
    )
    new_orgs = (
        db.query(func.count(Organization.id)).filter(Organization.created_at >= cutoff).scalar()
        or 0
    )

    plan_rows = (
        db.query(Organization.plan, func.count(Organization.id)).group_by(Organization.plan).all()
    )
    plan_counts = {plan: count for plan, count in plan_rows}
    plan_distribution = {key: int(plan_counts.get(key, 0)) for key in _PLAN_KEYS}

    # ── Usage: executions in window ───────────────────────────────────────
    exec_window = [ModelExecution.created_at >= cutoff]

    total_executions = db.query(func.count(ModelExecution.id)).filter(*exec_window).scalar() or 0
    distinct_users = (
        db.query(func.count(func.distinct(ModelExecution.executed_by_user_id)))
        .filter(*exec_window, ModelExecution.executed_by_user_id.isnot(None))
        .scalar()
        or 0
    )
    distinct_orgs = (
        db.query(func.count(func.distinct(ModelExecution.organization_id)))
        .filter(*exec_window)
        .scalar()
        or 0
    )

    status_rows = (
        db.query(ModelExecution.status, func.count(ModelExecution.id))
        .filter(*exec_window)
        .group_by(ModelExecution.status)
        .all()
    )
    by_status = {status: int(count) for status, count in status_rows}

    origin_rows = (
        db.query(ModelExecution.origin, func.count(ModelExecution.id))
        .filter(*exec_window)
        .group_by(ModelExecution.origin)
        .all()
    )
    by_origin = {(origin or "manual"): int(count) for origin, count in origin_rows}

    solver_rows = (
        db.query(ModelExecution.solver_name, func.count(ModelExecution.id))
        .filter(*exec_window)
        .group_by(ModelExecution.solver_name)
        .all()
    )
    by_solver = {(name or "unknown"): int(count) for name, count in solver_rows}

    time_filter = [*exec_window, ModelExecution.execution_time_ms.isnot(None)]
    avg_solve = db.query(func.avg(ModelExecution.execution_time_ms)).filter(*time_filter).scalar()
    median_solve = (
        db.query(func.percentile_cont(0.5).within_group(ModelExecution.execution_time_ms))
        .filter(*time_filter)
        .scalar()
    )

    # Builder / ad-hoc solves: executions with no catalog/org model attached
    # (organization_model_id NULL — the /solve path used by the visual builder and
    # the LLM "Solve"), as opposed to catalog/marketplace model executions.
    builder_filter = [*exec_window, ModelExecution.organization_model_id.is_(None)]
    builder_total = db.query(func.count(ModelExecution.id)).filter(*builder_filter).scalar() or 0
    builder_completed = (
        db.query(func.count(ModelExecution.id))
        .filter(*builder_filter, ModelExecution.status == "completed")
        .scalar()
        or 0
    )
    builder_avg = (
        db.query(func.avg(ModelExecution.execution_time_ms))
        .filter(*builder_filter, ModelExecution.execution_time_ms.isnot(None))
        .scalar()
    )

    # ── Per-category breakdown (executions → org_model → catalog.category) ─
    category_col = func.coalesce(ModelCatalog.category, "custom")
    completed_sum = func.sum(case((ModelExecution.status == "completed", 1), else_=0))
    cat_rows = (
        db.query(
            category_col.label("category"),
            func.count(ModelExecution.id).label("executions"),
            func.avg(ModelExecution.execution_time_ms).label("avg_ms"),
            completed_sum.label("completed"),
        )
        .select_from(ModelExecution)
        .outerjoin(
            OrganizationModel,
            ModelExecution.organization_model_id == OrganizationModel.id,
        )
        .outerjoin(ModelCatalog, OrganizationModel.catalog_id == ModelCatalog.id)
        .filter(*exec_window)
        .group_by(category_col)
        .order_by(func.count(ModelExecution.id).desc())
        .all()
    )
    by_category = [
        {
            "category": category,
            "executions": int(executions),
            "avg_solve_time_ms": float(avg_ms) if avg_ms is not None else None,
            "success_rate": _ratio(int(completed or 0), int(executions)),
        }
        for category, executions, avg_ms, completed in cat_rows
    ]

    # ── Daily trend (platform-wide executions/day) ────────────────────────
    day_col = func.date(ModelExecution.created_at)
    daily_rows = (
        db.query(day_col.label("d"), func.count(ModelExecution.id))
        .filter(*exec_window)
        .group_by(day_col)
        .order_by(day_col)
        .all()
    )
    daily = [{"date": str(day), "executions": int(count)} for day, count in daily_rows]

    return {
        "days": days,
        "users": {"total": int(total_users), "active": int(active_users), "new": int(new_users)},
        "orgs": {"total": int(total_orgs), "active": int(active_orgs), "new": int(new_orgs)},
        "avg_users_per_org": _ratio(int(total_users), int(total_orgs)),
        "plan_distribution": plan_distribution,
        "executions": {
            "total": int(total_executions),
            "per_user": _ratio(int(total_executions), int(distinct_users)),
            "per_org": _ratio(int(total_executions), int(distinct_orgs)),
            "success_rate": _ratio(int(by_status.get("completed", 0)), int(total_executions)),
            "avg_solve_time_ms": float(avg_solve) if avg_solve is not None else None,
            "median_solve_time_ms": float(median_solve) if median_solve is not None else None,
            "by_status": by_status,
            "by_origin": by_origin,
            "by_solver": by_solver,
        },
        "builder_solves": {
            "total": int(builder_total),
            "success_rate": _ratio(int(builder_completed), int(builder_total)),
            "avg_solve_time_ms": float(builder_avg) if builder_avg is not None else None,
        },
        "by_category": by_category,
        "daily": daily,
    }


def compute_reliability(db: Session, days: int) -> dict[str, Any]:
    """SLO percentiles, failure modes, queue time, and automation health."""
    cutoff = _cutoff(days)
    exec_window = [ModelExecution.created_at >= cutoff]

    total = db.query(func.count(ModelExecution.id)).filter(*exec_window).scalar() or 0

    pct = (
        db.query(
            func.percentile_cont(0.5).within_group(ModelExecution.execution_time_ms),
            func.percentile_cont(0.95).within_group(ModelExecution.execution_time_ms),
            func.percentile_cont(0.99).within_group(ModelExecution.execution_time_ms),
        )
        .filter(*exec_window, ModelExecution.execution_time_ms.isnot(None))
        .one()
    )
    percentiles = {
        "p50": float(pct[0]) if pct[0] is not None else None,
        "p95": float(pct[1]) if pct[1] is not None else None,
        "p99": float(pct[2]) if pct[2] is not None else None,
    }

    status_rows = (
        db.query(ModelExecution.status, func.count(ModelExecution.id))
        .filter(*exec_window)
        .group_by(ModelExecution.status)
        .all()
    )
    by_status = {status: int(count) for status, count in status_rows}
    timed_out = by_status.get("timeout", 0)
    failed = by_status.get("failed", 0)

    fail_rows = (
        db.query(ModelExecution.solver_status, func.count(ModelExecution.id))
        .filter(*exec_window, ModelExecution.status.in_(("failed", "timeout")))
        .group_by(ModelExecution.solver_status)
        .order_by(func.count(ModelExecution.id).desc())
        .all()
    )
    failures_by_solver_status = {
        (solver_status or "unknown"): int(count) for solver_status, count in fail_rows
    }

    # Queue time = avg seconds between created_at and started_at.
    queue_seconds = (
        db.query(
            func.avg(func.extract("epoch", ModelExecution.started_at - ModelExecution.created_at))
        )
        .filter(*exec_window, ModelExecution.started_at.isnot(None))
        .scalar()
    )

    async_count = (
        db.query(func.count(ModelExecution.id))
        .filter(*exec_window, ModelExecution.is_async.is_(True))
        .scalar()
        or 0
    )

    # ── Automation: triggers / runs / schedules ───────────────────────────
    total_triggers = db.query(func.count(SolveTrigger.id)).scalar() or 0
    active_triggers = (
        db.query(func.count(SolveTrigger.id)).filter(SolveTrigger.is_enabled.is_(True)).scalar()
        or 0
    )
    run_window = [TriggerRun.created_at >= cutoff]
    total_runs = db.query(func.count(TriggerRun.id)).filter(*run_window).scalar() or 0
    cron_total = (
        db.query(func.count(TriggerRun.id))
        .filter(*run_window, TriggerRun.source == "cron")
        .scalar()
        or 0
    )
    cron_completed = (
        db.query(func.count(TriggerRun.id))
        .filter(*run_window, TriggerRun.source == "cron", TriggerRun.status == "completed")
        .scalar()
        or 0
    )
    webhook_attempted = (
        db.query(func.count(TriggerRun.id))
        .filter(*run_window, TriggerRun.webhook_delivered.isnot(None))
        .scalar()
        or 0
    )
    webhook_delivered = (
        db.query(func.count(TriggerRun.id))
        .filter(*run_window, TriggerRun.webhook_delivered.is_(True))
        .scalar()
        or 0
    )
    schedules_failing = (
        db.query(func.count(TriggerSchedule.id))
        .filter(TriggerSchedule.consecutive_failures > 0)
        .scalar()
        or 0
    )

    low_rows = (
        db.query(
            ModelCatalog.id,
            ModelCatalog.display_name,
            ModelCatalog.category,
            ModelCatalog.success_rate,
            ModelCatalog.total_executions,
        )
        .filter(
            ModelCatalog.success_rate.isnot(None),
            ModelCatalog.success_rate < _LOW_SUCCESS_THRESHOLD,
            ModelCatalog.total_executions >= _LOW_SUCCESS_MIN_EXECUTIONS,
        )
        .order_by(ModelCatalog.success_rate.asc())
        .limit(10)
        .all()
    )
    low_success_models = [
        {
            "id": cid,
            "display_name": display_name,
            "category": category,
            "success_rate": float(success_rate),
            "total_executions": int(total_executions),
        }
        for cid, display_name, category, success_rate, total_executions in low_rows
    ]

    return {
        "days": days,
        "total_executions": int(total),
        "percentiles_ms": percentiles,
        "timeout_rate": _ratio(int(timed_out), int(total)),
        "failure_rate": _ratio(int(failed), int(total)),
        "failures_by_solver_status": failures_by_solver_status,
        "avg_queue_time_s": float(queue_seconds) if queue_seconds is not None else None,
        "async_count": int(async_count),
        "sync_count": int(total) - int(async_count),
        "automation": {
            "total_triggers": int(total_triggers),
            "active_triggers": int(active_triggers),
            "total_runs": int(total_runs),
            "cron_success_rate": _ratio(int(cron_completed), int(cron_total)),
            "webhook_delivery_rate": _ratio(int(webhook_delivered), int(webhook_attempted)),
            "schedules_failing": int(schedules_failing),
        },
        "low_success_models": low_success_models,
    }


def compute_ai_usage(db: Session, days: int) -> dict[str, Any]:
    """LLM adoption, token/cost totals, acceptance rate, and thumbs ratings."""
    cutoff = _cutoff(days)
    conv_window = [LLMConversation.created_at >= cutoff]

    conversations = db.query(func.count(LLMConversation.id)).filter(*conv_window).scalar() or 0
    orgs_using_ai = (
        db.query(func.count(func.distinct(LLMConversation.organization_id)))
        .filter(*conv_window)
        .scalar()
        or 0
    )
    accepted = (
        db.query(func.count(LLMConversation.id))
        .filter(*conv_window, LLMConversation.organization_model_id.isnot(None))
        .scalar()
        or 0
    )

    msg_window = [LLMMessage.created_at >= cutoff]
    messages = db.query(func.count(LLMMessage.id)).filter(*msg_window).scalar() or 0
    total_input = db.query(func.sum(LLMMessage.input_tokens)).filter(*msg_window).scalar() or 0
    total_output = db.query(func.sum(LLMMessage.output_tokens)).filter(*msg_window).scalar() or 0
    total_cost = db.query(func.sum(LLMMessage.cost_eur)).filter(*msg_window).scalar()
    total_cost_eur = float(total_cost) if total_cost is not None else 0.0

    rating_rows = (
        db.query(FormulationRating.rating, func.count(FormulationRating.id))
        .filter(FormulationRating.created_at >= cutoff)
        .group_by(FormulationRating.rating)
        .all()
    )
    ratings = {rating: int(count) for rating, count in rating_rows}
    thumbs_up = ratings.get("up", 0)
    thumbs_down = ratings.get("down", 0)

    return {
        "days": days,
        "conversations": int(conversations),
        "messages": int(messages),
        "orgs_using_ai": int(orgs_using_ai),
        "total_input_tokens": int(total_input),
        "total_output_tokens": int(total_output),
        "total_cost_eur": round(total_cost_eur, 4),
        "avg_cost_per_conversation": round(_ratio(total_cost_eur, int(conversations)), 4),
        "messages_per_conversation": _ratio(int(messages), int(conversations)),
        "accepted_conversations": int(accepted),
        "acceptance_rate": _ratio(int(accepted), int(conversations)),
        "thumbs_up": thumbs_up,
        "thumbs_down": thumbs_down,
        "thumbs_ratio": _ratio(thumbs_up, thumbs_up + thumbs_down),
    }
