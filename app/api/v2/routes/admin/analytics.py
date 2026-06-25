"""Platform-wide analytics endpoints for admins.

Aggregations span ALL organizations (no per-org tenancy filter) — these are
mounted under the admin router, which gates every route with ``get_admin_user``
(HTTP 403 for non-admins). Backed by ``app.services.platform_analytics_service``.

  GET /admin/platform/overview?days=30
  GET /admin/platform/reliability?days=30
  GET /admin/platform/ai?days=30
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import DBSession
from app.services import platform_analytics_service as svc

router = APIRouter(prefix="/platform", tags=["admin-platform-analytics"])

_DAYS = Query(30, ge=0, le=365, description="Look-back window in days (0 = all time)")


# ── Overview ──────────────────────────────────────────────────────────────
class EntityCounts(BaseModel):
    total: int
    active: int
    new: int


class ExecutionStats(BaseModel):
    total: int
    per_user: float
    per_org: float
    success_rate: float
    avg_solve_time_ms: float | None
    median_solve_time_ms: float | None
    by_status: dict[str, int]
    by_origin: dict[str, int]
    by_solver: dict[str, int]


class BuilderSolves(BaseModel):
    total: int
    success_rate: float
    avg_solve_time_ms: float | None


class CategoryStat(BaseModel):
    category: str
    executions: int
    avg_solve_time_ms: float | None
    success_rate: float


class DailyPoint(BaseModel):
    date: str
    executions: int


class PlatformOverviewResponse(BaseModel):
    days: int
    users: EntityCounts
    orgs: EntityCounts
    avg_users_per_org: float
    plan_distribution: dict[str, int]
    executions: ExecutionStats
    builder_solves: BuilderSolves
    by_category: list[CategoryStat]
    daily: list[DailyPoint]


# ── Reliability ─────────────────────────────────────────────────────────────
class Percentiles(BaseModel):
    p50: float | None
    p95: float | None
    p99: float | None


class AutomationStats(BaseModel):
    total_triggers: int
    active_triggers: int
    total_runs: int
    cron_success_rate: float
    webhook_delivery_rate: float
    schedules_failing: int


class LowSuccessModel(BaseModel):
    id: str
    display_name: str
    category: str
    success_rate: float
    total_executions: int


class ReliabilityResponse(BaseModel):
    days: int
    total_executions: int
    percentiles_ms: Percentiles
    timeout_rate: float
    failure_rate: float
    failures_by_solver_status: dict[str, int]
    avg_queue_time_s: float | None
    async_count: int
    sync_count: int
    automation: AutomationStats
    low_success_models: list[LowSuccessModel]


# ── AI / LLM ────────────────────────────────────────────────────────────────
class AiUsageResponse(BaseModel):
    days: int
    conversations: int
    messages: int
    orgs_using_ai: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_eur: float
    avg_cost_per_conversation: float
    messages_per_conversation: float
    accepted_conversations: int
    acceptance_rate: float
    thumbs_up: int
    thumbs_down: int
    thumbs_ratio: float


@router.get(
    "/overview",
    response_model=PlatformOverviewResponse,
    operation_id="get_platform_overview",
)
async def get_platform_overview(db: DBSession, days: int = _DAYS) -> PlatformOverviewResponse:
    """Growth, usage, and per-category breakdown across the whole platform."""
    return PlatformOverviewResponse(**svc.compute_platform_overview(db, days))


@router.get(
    "/reliability",
    response_model=ReliabilityResponse,
    operation_id="get_platform_reliability",
)
async def get_platform_reliability(db: DBSession, days: int = _DAYS) -> ReliabilityResponse:
    """SLO percentiles, failure modes, queue time, and automation health."""
    return ReliabilityResponse(**svc.compute_reliability(db, days))


@router.get(
    "/ai",
    response_model=AiUsageResponse,
    operation_id="get_platform_ai_usage",
)
async def get_platform_ai_usage(db: DBSession, days: int = _DAYS) -> AiUsageResponse:
    """LLM adoption, token/cost totals, acceptance rate, and thumbs ratings."""
    return AiUsageResponse(**svc.compute_ai_usage(db, days))
