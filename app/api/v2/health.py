"""Health check and metrics endpoints for API v2."""

import logging
import platform
import time
from threading import Lock
from typing import Any

import psutil
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.schemas.health import RecentRequestEntry, RecentRequestsResponse
from app.shared.core.metrics import metrics_collector
from app.version import APP_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

# Re-export the Hexaly worker probe from the domain-friendly module so the
# /health/status handler keeps a stable reference target. Extraction breaks
# the solver.services -> api.v2.health -> pyscipopt import-linter cycle.
from app.domains.solver.services.worker_health import _probe_hexaly_worker  # noqa: E402, F401

# MAINTENANCE_MODE TTL cache (D-7.1-13, E-13). Mirrors _hexaly_probe_cache.
# Scope: /health handler only. DO NOT generalize into a cross-cutting PSS
# read-through cache (explicit anti-pattern per D-7.1-13).
_MAINTENANCE_PROBE_CACHE_SECONDS = 10.0
_maintenance_probe_cache: tuple[float, bool] | None = None
_maintenance_probe_lock = Lock()


def _probe_maintenance_mode() -> bool:
    """TTL-cached PlatformSettingsService.get_bool('MAINTENANCE_MODE').

    Uses a 10s TTL + single-flight lock so that sustained healthcheck load
    (e.g. k8s liveness probes every 10s across N replicas) invokes
    PSS.get_bool at most once per 10s per process — not on every /health hit.

    D-25: this helper owns its session instead of receiving one from
    ``Depends(get_db)``. FastAPI resolves dependencies *before* entering the
    handler, so the old signature checked out a pooled connection on **every**
    health request — including the ~9 out of 10 that the TTL cache serves
    without touching the database at all. Under saturation that made the health
    check queue behind ordinary traffic, which is how a slow API became a
    restarting one.

    All errors are swallowed: on failure we serve the last known value, or
    False (maintenance off) if we have never had one. A saturated pool or a
    broken platform_settings row must not stop the health endpoint answering.
    """
    global _maintenance_probe_cache

    with _maintenance_probe_lock:
        now = time.monotonic()
        cached = _maintenance_probe_cache
        if cached is not None and (now - cached[0]) < _MAINTENANCE_PROBE_CACHE_SECONDS:
            return cached[1]

        from app.services.platform_settings_service import PlatformSettingsService
        from app.shared.db.session import SessionLocal

        try:
            db = SessionLocal()
            try:
                is_maintenance = PlatformSettingsService.get_bool(
                    db,
                    "MAINTENANCE_MODE",
                    default=False,
                )
            finally:
                db.close()
        except Exception:  # noqa: BLE001 — infra probe must degrade, never raise
            # Stale-if-error: an exhausted pool is exactly when the flag matters
            # least and answering matters most.
            return cached[1] if cached is not None else False

        _maintenance_probe_cache = (now, is_maintenance)
        return is_maintenance


class SystemMetrics(BaseModel):
    """System resource metrics."""

    cpu_percent: float = Field(..., description="CPU usage percentage")
    memory_percent: float = Field(..., description="Memory usage percentage")
    memory_available_mb: float = Field(..., description="Available memory in MB")
    disk_usage_percent: float = Field(..., description="Disk usage percentage")


class HealthResponse(BaseModel):
    """Health check response with system metrics."""

    status: str
    version: str
    solver: str
    system: SystemMetrics
    uptime_seconds: float
    python_version: str
    maintenance: bool = False


class MetricsResponse(BaseModel):
    """Application metrics response."""

    uptime_seconds: float
    start_time: str
    total_requests: int
    total_successful: int
    total_failed: int
    problem_stats: dict[str, Any]


@router.get("", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Check API health and readiness with system metrics.

    Returns detailed health information including:
    - Solver status
    - System resource usage (CPU, memory, disk)
    - Application uptime
    - Python version
    - Maintenance mode flag

    Takes no DB session (D-25): the maintenance flag is read behind a 10s TTL
    cache that opens its own short-lived session, so a health check no longer
    checks out a pooled connection on every call.
    """
    # interval=None is REQUIRED here, not a preference: interval=0.1 sleeps 100ms
    # inside the call, and this handler runs on the event loop, so every health
    # check froze the whole worker for that long. This endpoint is the most-called
    # one in the system (the container health check polls it, and that traffic is
    # classified internal, hence exempt from the public rate limit).
    # interval=None reads the CPU delta since the previous call in this process
    # instead of sampling, which for a polled endpoint is the more meaningful
    # number anyway (average over the polling gap, not a 100ms snapshot).
    # The counter is primed at startup so the first request is not 0.0.
    cpu_percent = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    app_stats = metrics_collector.get_stats()

    is_maintenance = _probe_maintenance_mode()

    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        solver="SCIP (universal)",
        system=SystemMetrics(
            cpu_percent=round(cpu_percent, 2),
            memory_percent=round(memory.percent, 2),
            memory_available_mb=round(memory.available / (1024 * 1024), 2),
            disk_usage_percent=round(disk.percent, 2),
        ),
        uptime_seconds=round(app_stats.get("uptime_seconds", 0), 2),
        python_version=platform.python_version(),
        maintenance=is_maintenance,
    )


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics() -> MetricsResponse:
    """Get application performance metrics."""
    stats = metrics_collector.get_stats()

    return MetricsResponse(
        uptime_seconds=round(stats["uptime_seconds"], 2),
        start_time=stats["start_time"],
        total_requests=stats["total_requests"],
        total_successful=stats["total_successful"],
        total_failed=stats["total_failed"],
        problem_stats=stats["problem_stats"],
    )


@router.get("/metrics/recent", response_model=RecentRequestsResponse)
def get_recent_requests(
    limit: int = Query(default=10, ge=1, le=100, description="Number of recent requests to return"),
) -> RecentRequestsResponse:
    """Get recent request history."""
    recent = metrics_collector.get_recent_requests(limit=limit)
    return RecentRequestsResponse(
        recent_requests=[RecentRequestEntry(**entry) for entry in recent],
        count=len(recent),
    )


class ComponentStatus(BaseModel):
    """Status of a single component."""

    name: str
    status: str  # "healthy", "degraded", "down"
    latency_ms: float | None = None
    message: str | None = None


class DetailedStatusResponse(BaseModel):
    """Detailed health status for SLA monitoring."""

    status: str  # "healthy", "degraded", "down"
    version: str
    uptime_seconds: float
    components: list[ComponentStatus]
    sla_target: str
    checks_passed: int
    checks_total: int


@router.get("/status", response_model=DetailedStatusResponse)
def detailed_status() -> DetailedStatusResponse:
    """Detailed health status with component checks.

    Used for SLA monitoring and uptime tracking. Checks:
    - Database connectivity
    - Solver availability
    - System resources (memory, disk)

    Returns overall status: healthy, degraded, or down.

    This is the endpoint the container health check polls, so it takes no DB
    session (D-25). ``Depends(get_db)`` used to check out a pooled connection
    before the handler ran: when the pool was exhausted the probe blocked for
    the full ``pool_timeout`` and Docker's 10s timeout expired, marking a
    merely-slow container unhealthy and restarting it — which moved its load
    onto the remaining workers. Acquiring the connection *inside* the check
    turns pool exhaustion into what it actually is: a reported "database is
    down", answered promptly, instead of a restart cascade.
    """
    import time

    components = []
    app_stats = metrics_collector.get_stats()

    # 1. Database check — owns its session, so exhaustion is reported, not queued on.
    try:
        from app.shared.db.session import SessionLocal

        t0 = time.monotonic()
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        db_latency = round((time.monotonic() - t0) * 1000, 2)
        components.append(
            ComponentStatus(
                name="database",
                status="healthy",
                latency_ms=db_latency,
            )
        )
    except SQLAlchemyTimeoutError as e:
        # Distinguish "no free connection" from "the database is unreachable":
        # they need different operator responses (raise the pool / bound
        # admission vs. go look at Postgres).
        logger.error("Health check: database pool exhausted: %s", e)
        components.append(
            ComponentStatus(
                name="database",
                status="down",
                message="connection pool exhausted (no free connection within pool_timeout)",
            )
        )
    except Exception as e:
        logger.error("Health check: database connectivity failed: %s", e)
        components.append(
            ComponentStatus(
                name="database",
                status="down",
                message=str(e)[:200],
            )
        )

    # 2. Solver check
    try:
        t0 = time.monotonic()
        from pyscipopt import Model

        m = Model("health_check")
        m.hideOutput()
        x = m.addVar("x", lb=0)
        m.setObjective(x, "minimize")
        m.addCons(x >= 1)
        m.optimize()
        solver_latency = round((time.monotonic() - t0) * 1000, 2)
        components.append(
            ComponentStatus(
                name="solver",
                status="healthy",
                latency_ms=solver_latency,
            )
        )
    except Exception as e:
        logger.error("Health check: solver availability failed: %s", e)
        components.append(
            ComponentStatus(
                name="solver",
                status="down",
                message=str(e)[:200],
            )
        )

    # 3. Hexaly worker availability (Phase 7 / D-21)
    #
    # Reports whether a Hexaly worker process in this deployment can serve
    # a solve: hexaly SDK importable (SDK present in this process/container)
    # AND Celery-ping responds on the dedicated ``solve_hexaly`` queue.
    # Intentionally does NOT query ``solver_licenses`` — /health is
    # infrastructure-only and must not depend on business data (D-21).
    #
    # When the API container itself does not carry the hexaly SDK (the usual
    # case — the SDK only ships in the ``jaot-worker-hexaly`` image),
    # ``sdk_importable`` is False and the status degrades to "down".
    # Operators running without the Hexaly worker see one degraded row;
    # operators running with it see a healthy row; nothing leaks about
    # per-org license state.
    try:
        from app.domains.solver.adapters.hexaly_availability import hexaly_available

        sdk_importable = hexaly_available()
    except Exception:  # noqa: BLE001 — defensive; any probe failure == unavailable
        sdk_importable = False

    hexaly_queue_ok = False
    hexaly_msg: str | None = None
    if sdk_importable:
        # inspect().active_queues() filtered for 'solve_hexaly' (naive ping()
        # would be answered by any SCIP / HiGHS worker on the broker too).
        # Short timeout + TTL cache keep a flapping broker from stalling us.
        hexaly_queue_ok, hexaly_msg = _probe_hexaly_worker()
    else:
        hexaly_msg = "Hexaly SDK not installed in this process"

    if hexaly_queue_ok and sdk_importable:
        hexaly_status = "healthy"
    else:
        # "degraded" rather than "down" — Hexaly is commercial/optional
        # and a JAOT deployment without it is still a valid configuration
        # (customers simply can't solve with solver_name="hexaly").
        hexaly_status = "degraded"
    components.append(
        ComponentStatus(
            name="solver_worker_hexaly",
            status=hexaly_status,
            message=hexaly_msg,
        )
    )

    # 4. Memory check (was #3 pre-Phase 7)
    memory = psutil.virtual_memory()
    mem_status = "healthy"
    mem_msg = None
    if memory.percent > 95:
        mem_status = "down"
        mem_msg = f"Memory usage critical: {memory.percent}%"
    elif memory.percent > 85:
        mem_status = "degraded"
        mem_msg = f"Memory usage high: {memory.percent}%"
    components.append(
        ComponentStatus(
            name="memory",
            status=mem_status,
            message=mem_msg,
        )
    )

    # 5. Disk check (was #4 pre-Phase 7)
    disk = psutil.disk_usage("/")
    disk_status = "healthy"
    disk_msg = None
    if disk.percent > 95:
        disk_status = "down"
        disk_msg = f"Disk usage critical: {disk.percent}%"
    elif disk.percent > 85:
        disk_status = "degraded"
        disk_msg = f"Disk usage high: {disk.percent}%"
    components.append(
        ComponentStatus(
            name="disk",
            status=disk_status,
            message=disk_msg,
        )
    )

    # Overall status
    statuses = [c.status for c in components]
    if "down" in statuses:
        overall = "down"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    healthy_count = sum(1 for s in statuses if s == "healthy")

    return DetailedStatusResponse(
        status=overall,
        version=APP_VERSION,
        uptime_seconds=round(app_stats.get("uptime_seconds", 0), 2),
        components=components,
        sla_target="99.9%",
        checks_passed=healthy_count,
        checks_total=len(components),
    )
