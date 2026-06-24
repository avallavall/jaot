"""Main application factory for JAOT."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

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

    Runs during startup after DB connection is verified.
    Never crashes the app -- logs and continues on failure.
    """
    from app.models.platform_setting import PlatformSetting
    from app.services.settings_registry import SETTINGS_REGISTRY
    from app.shared.db.session import SessionLocal

    db = SessionLocal()
    try:
        missing = 0
        for defn in SETTINGS_REGISTRY:
            if defn.default_value is None:
                continue
            exists = db.query(PlatformSetting).filter(PlatformSetting.key == defn.key).first()
            if not exists:
                db.add(
                    PlatformSetting(
                        key=defn.key,
                        value=defn.default_value,
                        description=defn.description,
                        updated_by="system_seed",
                    )
                )
                missing += 1
        if missing:
            db.commit()
            logger.warning(
                "Self-healed %d missing platform settings from registry",
                missing,
            )
        else:
            logger.info("All platform settings present in database")
    except Exception as e:
        logger.error("Failed to self-heal settings: %s", e)
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for startup and shutdown events."""
    from app.services.platform_settings_service import (
        PlatformSettingsService as PSS,
    )
    from app.shared.db.session import SessionLocal

    # Self-heal: ensure all registry settings exist in DB (do first)
    _ensure_settings_seeded()

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

        # Configure Stripe if keys are set
        stripe_key = PSS.get_str(startup_db, "STRIPE_SECRET_KEY")
        if stripe_key:
            try:
                from app.services.stripe_service import StripeService

                webhook_secret = PSS.get_str(startup_db, "STRIPE_WEBHOOK_SECRET")

                plan_prices = {}
                for plan in ("starter", "pro", "business"):
                    key = f"STRIPE_PRICE_{plan.upper()}_MONTHLY"
                    val = PSS.get_str(startup_db, key)
                    if val:
                        plan_prices[plan] = val

                topup_prices = {}
                for amount in (500, 2000, 5000, 20000):
                    key = f"STRIPE_PRICE_TOPUP_{amount}"
                    val = PSS.get_str(startup_db, key)
                    if val:
                        topup_prices[amount] = val

                StripeService.configure(
                    secret_key=stripe_key,
                    webhook_secret=webhook_secret,
                    plan_price_ids=plan_prices,
                    topup_price_ids=topup_prices,
                )
                logger.info("💳 Stripe billing configured")
            except Exception as e:
                logger.warning(f"⚠️ Stripe configuration failed: {e}")
        else:
            logger.info("💳 Stripe not configured (STRIPE_SECRET_KEY not set)")

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
        version="2.0.0",
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

    return app


app = create_app()
