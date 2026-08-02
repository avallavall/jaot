"""Main application factory for JAOT."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v2.router import api_v2_router
from app.config import settings
from app.shared.core.auth_middleware import ASGIAuthMiddleware
from app.shared.core.body_limit import BodyLimitMiddleware
from app.shared.core.maintenance_middleware import MaintenanceMiddleware
from app.shared.core.security_headers import SecurityHeadersMiddleware
from app.version import APP_VERSION

# Configure logging
log_level = logging.DEBUG if settings.DEBUG else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# Third-party HTTP/ML libraries emit extremely verbose DEBUG (full request headers,
# model-weight loading) that drowns the app's own logs when DEBUG=True. Pin them to
# WARNING so `docker compose logs` stays readable without losing app-level DEBUG.
for _noisy in ("httpcore", "httpx", "huggingface_hub", "urllib3", "filelock"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _ensure_settings_seeded() -> None:
    """Insert missing platform settings from registry defaults.

    Runs during startup after DB connection is verified. The API boots
    several uvicorn workers concurrently, so this races: without a guard,
    every worker reads the same key as missing and 3-of-4 fail the unique
    key PK with ``UniqueViolation``. The insert therefore uses
    ``ON CONFLICT DO NOTHING`` — the ``missing`` probe is a cheap best-effort
    filter, the conflict clause is what actually makes it race-safe.
    Never crashes the app -- logs and continues on failure.
    """
    from sqlalchemy import update as sa_update
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.platform_setting import PlatformSetting
    from app.services.settings_registry import SETTINGS_REGISTRY
    from app.shared.db.session import SessionLocal
    from app.shared.utils.datetime_helpers import utcnow

    db = SessionLocal()
    try:
        existing = {key for (key,) in db.query(PlatformSetting.key).all()}
        now = utcnow()

        # Readonly settings mirror code constants (APP_VERSION, JWT_ALGORITHM) —
        # refresh them to the registry default on every boot. The insert below only
        # covers MISSING keys, so after an upgrade a readonly row would otherwise
        # keep the value of whichever release first seeded it (an admin panel
        # forever showing the old version).
        refreshed = 0
        for defn in SETTINGS_REGISTRY:
            if not (defn.is_readonly and defn.default_value is not None):
                continue
            result = db.execute(
                sa_update(PlatformSetting)
                .where(
                    PlatformSetting.key == defn.key,
                    PlatformSetting.value != defn.default_value,
                )
                .values(value=defn.default_value, updated_at=now, updated_by="system_seed")
            )
            refreshed += result.rowcount or 0
        if refreshed:
            db.commit()
            logger.warning(
                "Refreshed %d readonly platform settings to their registry defaults", refreshed
            )

        rows = [
            {
                "key": defn.key,
                "value": defn.default_value,
                "description": defn.description,
                "updated_at": now,
                "updated_by": "system_seed",
            }
            for defn in SETTINGS_REGISTRY
            if defn.default_value is not None and defn.key not in existing
        ]
        if not rows:
            logger.info("All platform settings present in database")
            return
        stmt = (
            pg_insert(PlatformSetting).values(rows).on_conflict_do_nothing(index_elements=["key"])
        )
        result = db.execute(stmt)
        db.commit()
        logger.warning(
            "Self-healed missing platform settings from registry (%d candidates, %d inserted)",
            len(rows),
            result.rowcount if result.rowcount and result.rowcount >= 0 else 0,
        )
    except Exception as e:
        logger.error("Failed to self-heal settings: %s", e)
        db.rollback()
    finally:
        db.close()


#: Connections held outside the request-scoped budget, so admission must stay
#: below pool capacity by at least this much: the maintenance probe and the
#: status collector (api/v2/health.py), the websocket progress reader
#: (api/v2/ws.py) and the execution writer (domains/solver/execution_writer.py).
_OUT_OF_BAND_SESSIONS = 4


def _configure_threadpool() -> None:
    """Bound concurrent request execution to what the DB pool can serve (D-25).

    Our endpoints are synchronous by design (ADR-009 moved them off the event
    loop deliberately, because import/export/validate is heavy SCIP work), so
    every request runs in the AnyIO threadpool. That threadpool defaulted to 40
    tokens per process and had never been tuned, while production gives each of
    its four worker processes a pool of 10 connections — so each process
    admitted four times the concurrent work it could actually serve.

    The surplus did not fail fast: an endpoint holds its connection for the
    whole request, so request 11 waited out ``pool_timeout`` and then 500'd,
    having occupied a thread the entire time.

    Matching tokens to pool capacity makes the queue land in one place, before
    the work starts, instead of stranding threads on a resource that is already
    fully committed.

    Admission stops SHORT of capacity, though. Not every connection is taken by
    a request: the health probe, the status collector, the websocket progress
    reader and the execution writer each open their own session outside the
    request-scoped budget. Admitting exactly `capacity` requests leaves those
    with nothing, so the health probe waits out ``pool_timeout`` and reports
    ``database: down`` — a busy API reported as a broken one, which is the exact
    symptom D-25 set out to remove.

    Never raises: a failure to tune the limiter must not stop the app booting —
    the old default is degraded, not broken.
    """
    try:
        import anyio.to_thread

        capacity = settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW
        configured = settings.API_THREADPOOL_TOKENS
        # Leave room for the out-of-band sessions above. On a tiny pool the
        # reserve would starve requests entirely, so never drop below one token.
        tokens = configured if configured > 0 else max(1, capacity - _OUT_OF_BAND_SESSIONS)
        if tokens <= 0:
            return

        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = tokens
        logger.info(
            "🧵 Request threadpool bounded to %d concurrent requests "
            "(was %s; DB pool capacity is %d, %d reserved for out-of-band sessions)",
            tokens,
            previous,
            capacity,
            capacity - tokens,
        )
    except Exception:
        logger.warning("Could not size the request threadpool; using the default", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for startup and shutdown events."""
    from app.services.platform_settings_service import (
        PlatformSettingsService as PSS,
    )
    from app.shared.db.session import SessionLocal
    from app.tasks.solver_ports import register_solver_ports

    # The API side of the solver domain's host ports (D-16). The worker side is
    # the Celery include list — miss either and the domain raises at first use.
    register_solver_ports()

    # D-25: make admission coherent with the connection pool. Must run inside
    # the running loop — the limiter lives in a RunVar, so setting it at import
    # time would configure a different loop's limiter (or none at all).
    _configure_threadpool()

    # Self-heal: ensure all registry settings exist in DB (do first)
    _ensure_settings_seeded()

    # Prime psutil's per-process CPU counter. /api/v2/health reads it with
    # interval=None (non-blocking — see health_check), which returns the delta
    # since the previous call and therefore 0.0 the very first time. Priming here
    # means the first real health check already reports a meaningful number.
    psutil.cpu_percent(interval=None)

    # Single DB session for all startup config reads
    startup_db = SessionLocal()
    try:
        try:
            app_name = PSS.get_str(startup_db, "APP_NAME")
        except Exception:
            app_name = "JAOT"

        # Startup
        logger.info(f"🚀 {app_name} started")
        logger.info("📦 Using universal SCIP solver for all optimization problems")

        # Initialize Redis for rate limiting
        from app.shared.core.rate_limiter import init_redis

        init_redis(settings.REDIS_URL)

        # Configure email service
        try:
            from app.services.email_service import EmailService

            EmailService.configure_from_pss(startup_db)
            email_backend = PSS.get_str(startup_db, "EMAIL_BACKEND")
            logger.info(f"📧 Email service configured: {email_backend}")

            if email_backend == "smtp":
                smtp_timeout = PSS.get_int(startup_db, "SMTP_TIMEOUT")
                is_valid, message = EmailService.verify_smtp_tls_handshake(
                    timeout=smtp_timeout,
                )
                if is_valid:
                    logger.info(f"📧 SMTP configuration validated: {message}")
                else:
                    logger.warning(
                        f"⚠️ SMTP configuration invalid: {message} — emails will fail to send"
                    )
        except Exception as e:
            logger.warning(f"⚠️ Email configuration failed: {e}")
    finally:
        startup_db.close()

    # Initialize RAG (Qdrant + Voyage) — best-effort, never blocks event loop
    try:
        import asyncio

        from app.services.rag.client import is_rag_available

        rag_ready = await asyncio.to_thread(is_rag_available)
        if rag_ready:
            logger.info("RAG knowledge base initialized (Qdrant + sentence-transformers)")
        else:
            logger.info("RAG not available (QDRANT_URL not set)")
    except Exception as e:
        logger.warning(f"RAG initialization skipped: {e}")

    # Start Redis WebSocket subscriber (best-effort, never blocks startup)
    try:
        from app.api.v2.ws import setup_redis_listener

        await setup_redis_listener()
        logger.info("🔌 Redis WebSocket subscriber initialized")
    except Exception as e:
        logger.warning(f"⚠️ Redis WebSocket subscriber failed to start: {e}")

    # Seed official model catalog (idempotent, non-blocking)
    try:
        from app.shared.db.seed_models import seed_official_models
        from app.shared.db.session import SessionLocal as _SL

        seed_db = _SL()
        try:
            count = seed_official_models(seed_db)
            seed_db.commit()
            logger.info(f"Seeded {count} catalog templates")
        finally:
            seed_db.close()
    except Exception as e:
        logger.warning(f"Template seeding skipped: {e}")

    # First-run admin bootstrap — no-op unless the users table is empty AND
    # SEED_ADMIN_* are configured (see app/shared/db/seed_admin.py)
    try:
        from app.shared.db.seed_admin import bootstrap_first_run
        from app.shared.db.session import SessionLocal as _SL2

        boot_db = _SL2()
        try:
            if bootstrap_first_run(boot_db):
                boot_db.commit()
            else:
                boot_db.rollback()
        finally:
            boot_db.close()
    except Exception as e:
        logger.warning(f"First-run admin bootstrap skipped: {e}")

    # Ensure Celery Beat tables exist
    try:
        from sqlalchemy_celery_beat.models import ModelBase as BeatModelBase

        from app.shared.db.session import engine

        BeatModelBase.metadata.create_all(engine)
        logger.info("Celery Beat tables ensured")
    except Exception as e:
        logger.warning(f"Beat table creation skipped: {e}")

    from app.shared.core.prometheus_metrics import init_app_info

    init_app_info()
    logger.info("📊 Prometheus metrics initialized")

    yield

    # Shutdown
    logger.info(f"🛑 {app_name} shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="JAOT",
        description="Universal optimization platform with SCIP solver",
        version=APP_VERSION,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # Phase 9: scoped 422 handler for /api/v2/contact. The handler itself
    # short-circuits to FastAPI's default for any other path, so global
    # registration is safe (I3 fix — single source of truth for validation
    # response shape stays in the framework default).
    from fastapi.exceptions import RequestValidationError

    from app.api.v2.contact import contact_validation_exception_handler

    app.add_exception_handler(RequestValidationError, contact_validation_exception_handler)

    # Errors that name themselves, so a localized client can render them without
    # printing the English `detail` (which is still sent, unchanged, for API and
    # MCP clients). Registered for the subclass only — plain HTTPException keeps
    # the framework default.
    from app.shared.core.http_errors import CodedHTTPException, coded_http_exception_handler

    app.add_exception_handler(CodedHTTPException, coded_http_exception_handler)

    # Add middleware (last added = outermost in request flow)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Authentication middleware -- always enabled, no bypass
    app.add_middleware(ASGIAuthMiddleware)
    logger.info("Authentication middleware enabled")

    # Maintenance mode gate
    app.add_middleware(MaintenanceMiddleware)

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodyLimitMiddleware)

    # Request ID middleware — generates/propagates X-Request-ID so errors
    # surfaced to clients (SSE error events, toasts) can be correlated with
    # server-side logs and metrics by support.
    from app.shared.core.request_id import RequestIdMiddleware

    app.add_middleware(RequestIdMiddleware)

    # CORS must be outermost
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=[
            "GET",
            "POST",
            "PUT",
            "DELETE",
            "PATCH",
            "OPTIONS",
        ],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
        ],
        expose_headers=[
            "X-Request-ID",
        ],
    )

    # Register solver adapters before routes so any route that resolves
    # a solver name at import time sees a populated registry. Phase 4 / D-09.
    from app.domains.solver.adapters import register_default_adapters

    register_default_adapters()
    logger.info("Solver adapters registered")

    # Include API router (all v2 endpoints including profiles and WebSocket)
    app.include_router(api_v2_router)
    logger.info("🔌 API v2 endpoints registered at /api/v2")

    # AI discovery routes
    from app.api.v2.llms import router as llms_router

    app.include_router(llms_router)
    logger.info("AI discovery routes registered at /.well-known/")

    # MCP server
    from app.mcp import setup_mcp

    setup_mcp(app)
    logger.info("MCP server mounted at /mcp")

    # Prometheus instrumentation
    try:
        from prometheus_client import REGISTRY as _PROM_REGISTRY

        stale = [
            c
            for name, c in list(_PROM_REGISTRY._names_to_collectors.items())
            if name.startswith("http_")
        ]
        for c in set(stale):
            try:
                _PROM_REGISTRY.unregister(c)
            except Exception:
                logger.debug(
                    "Failed to unregister stale Prometheus collector",
                    exc_info=True,
                )
    except Exception:
        logger.debug("Prometheus collector cleanup skipped", exc_info=True)

    Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        excluded_handlers=[
            "/metrics",
            ".*docs.*",
            ".*redoc.*",
            ".*openapi.*",
        ],
        should_instrument_requests_inprogress=True,
        inprogress_name="http_requests_inprogress",
        inprogress_labels=True,
    ).instrument(app).expose(app, include_in_schema=False, should_gzip=False)
    logger.info("📊 Prometheus /metrics endpoint exposed")

    # W17: jaot_llm_cost_eur_month / jaot_llm_budget_eur gauges (scrape-time
    # collector with ~60s in-process cache; idempotent across create_app calls).
    from app.shared.core.llm_budget_metrics import register_llm_budget_collector

    register_llm_budget_collector()

    # D-25: jaot_db_pool_* gauges. The connection pool reached no metric at all,
    # so exhaustion was invisible until a request timed out and 500'd.
    from app.shared.core.db_pool_metrics import register_db_pool_collector

    register_db_pool_collector()

    return app


app = create_app()
