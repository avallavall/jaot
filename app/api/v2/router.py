"""API v2 Router - Aggregates all v2 endpoints."""

from fastapi import APIRouter

from app.api.v2 import (
    auth,
    billing,
    builder,
    community,
    contact,
    credits,
    feedback,
    gdpr,
    guidance,
    health,
    home,
    keys,
    llm,
    notifications,
    pricing,
    schedules,
    seller,
    solve,
    solvers,
    triggers,
)
from app.api.v2.routes.admin import router as admin_router
from app.api.v2.routes.models import router as models_router
from app.api.v2.routes.profiles import router as profiles_router
from app.api.v2.routes.workspaces import router as workspaces_router
from app.api.v2.ws import router as ws_router
from app.domains.solver.routes import router as solve_templates_router

api_v2_router = APIRouter(prefix="/api/v2")

# Models - Unified optimization model system (catalog + activated + executions)
# Now using modular structure from app/api/v2/routes/models/
api_v2_router.include_router(models_router, tags=["models"])

# Solve endpoint - Universal optimization solver
api_v2_router.include_router(solve.router, tags=["solve"])

# Solvers — list available solver adapters (Phase 5 / HIGH-05)
api_v2_router.include_router(solvers.router, tags=["solvers"])

# Solve sub-router - Template endpoints (metadata, templates list/detail/solve)
api_v2_router.include_router(solve_templates_router, prefix="/solve", tags=["solve"])

# Credits - Credit management, withdrawals, exchange rates
api_v2_router.include_router(credits.router, tags=["credits"])

# API Keys - Key management
api_v2_router.include_router(keys.router, tags=["api-keys"])

# Admin endpoints - Now using modular structure from app/api/v2/routes/admin/
api_v2_router.include_router(admin_router, prefix="/admin", tags=["admin"])

# Auth endpoints
api_v2_router.include_router(auth.router, prefix="/auth", tags=["auth"])

# Health check and metrics
api_v2_router.include_router(health.router, tags=["health"])

# Notifications
api_v2_router.include_router(notifications.router, tags=["notifications"])

# Billing (Stripe)
api_v2_router.include_router(billing.router, tags=["billing"])

# Builder — visual model builder CRUD
api_v2_router.include_router(builder.router, tags=["builder"])

# Triggers — HTTP event triggers for async solve runs
api_v2_router.include_router(triggers.router, tags=["triggers"])

# LLM — natural language formulation generation with SSE streaming
api_v2_router.include_router(llm.router, tags=["llm"])

# Guidance — skill level and onboarding wizard state
api_v2_router.include_router(guidance.router, tags=["guidance"])

# Feedback — LLM formulation ratings
api_v2_router.include_router(feedback.router, tags=["feedback"])

# Community — DiscourseConnect SSO and community status
api_v2_router.include_router(community.router, tags=["community"])

# GDPR — data export and account deletion
api_v2_router.include_router(gdpr.router, tags=["gdpr"])

# Schedules — cron scheduling for triggers (CRUD + validation)
api_v2_router.include_router(schedules.router, tags=["schedules"])

# Seller — seller earnings dashboard endpoints
api_v2_router.include_router(seller.router, tags=["seller"])

# Pricing — public pricing data (no auth required)
api_v2_router.include_router(pricing.router, tags=["pricing"])

# Home — public announcement banner (no auth required)
api_v2_router.include_router(home.router, tags=["home"])

# Contact — public contact form submission (no auth required, opportunistic auth via middleware)
api_v2_router.include_router(contact.router, tags=["contact"])

# Workspaces — team collaboration, member management, invites, audit, credit pools
api_v2_router.include_router(workspaces_router, prefix="/workspaces", tags=["workspaces"])

# Profiles — public org/user profiles, reviews, admin profile management
api_v2_router.include_router(profiles_router, tags=["profiles"])

# WebSocket — real-time execution monitoring
api_v2_router.include_router(ws_router, tags=["websocket"])
