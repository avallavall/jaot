"""MCP server integration for JAOT Optimization Platform.

Exposes 30 curated optimization tools via the Model Context Protocol (MCP),
enabling AI agents (Claude, GPT, etc.) to discover and use JAOT's
optimization capabilities: multi-solver solving, multi-objective (Pareto),
templates, standard-format import/export (MPS/LP/CIP/JSON), the model
marketplace, execution insights, and first-class **model projects**
(create, author the draft, version with commit messages, analyze
stats/health, and solve).

P1.5 fusion: the legacy ``activate_catalog_model`` tool is retired — using a
marketplace model means seeding a fork ModelProject
(``create_model_project_from_marketplace``); ``execute_model`` executes a
ModelProject. G7d closes the agent-authoring loop:
``update_model_project_draft`` lets an agent WRITE the model (not just
create/commit/solve), and the solve tools accept ``solution_filter=nonzero``
for a compact solution that fits an MCP client's token budget.
"""

import logging
from typing import Any

from fastapi import FastAPI
from fastapi_mcp import FastApiMCP

from app.shared.constants.event_types import MCP_TOOL_CALL

logger = logging.getLogger(__name__)


def setup_mcp(app: FastAPI) -> FastApiMCP:
    """Initialize and mount MCP server exposing curated optimization tools."""
    mcp = FastApiMCP(
        app,
        name="JAOT Optimization Platform",
        description=(
            "Solve linear (LP) and mixed-integer (MIP) optimization problems with "
            "a choice of solvers (SCIP, HiGHS, Hexaly) or automatic routing, "
            "including multi-objective (Pareto) solves. Import and export models in "
            "standard formats (MPS/LP/CIP/JSON). Browse and run a marketplace of "
            "pre-built models, and inspect result insights. Create, version "
            "(git-style commits), analyze (stats + health score) and solve "
            "first-class model projects. Analyse a solved run exactly (binding "
            "constraints, slack, objective contributions), diagnose an infeasible "
            "one (minimal conflicting set), and measure what-if scenarios by real "
            "re-solves (what one more unit of a limit is worth, what overruling a "
            "decision costs). "
            "Authenticate with a Bearer API key."
        ),
        include_operations=[
            # Solve
            "solve_problem",
            "validate_problem",
            "solve_multi_objective",
            "list_available_solvers",
            # Templates
            "list_templates",
            "get_template",
            "solve_with_template",
            # File I/O — standard formats (MPS/LP/CIP/JSON)
            "import_preview",
            "import_and_solve",
            "export_model",
            "export_execution",
            # Marketplace
            "list_catalog_models",
            "get_catalog_model",
            "get_catalog_model_schema",
            # Execution & analysis. The analyses are the technical surface only —
            # binding rows, an IIS, measured what-if deltas. The plain-language
            # explain-* endpoints stay OUT on purpose: an MCP client is already a
            # model, so spending the platform's AI budget to narrate numbers it
            # can read itself would be paying twice for the same sentence.
            "execute_model",
            "get_execution",
            "get_execution_insights",
            "get_execution_exact_analysis",
            "analyze_infeasibility",
            # What-if (Sensitivity L2) is a batch of real re-solves: start it, then
            # poll — the same enqueue/poll shape an async solve already uses. The
            # claim is idempotent, so an agent's retry joins the batch in flight
            # instead of buying a second one.
            "start_execution_scenario_analysis",
            "get_execution_scenario_analysis",
            # Model projects — create, author, version, analyze & solve a first-class model
            "create_model_project",
            "create_model_project_from_marketplace",
            "get_model_project",
            "list_model_projects",
            "update_model_project_draft",
            "commit_model_version",
            "list_project_versions",
            "get_model_stats",
            "solve_model_project",
        ],
        describe_all_responses=True,
        describe_full_response_schema=True,
    )
    _install_tool_call_analytics(mcp)
    mcp.mount_http(mount_path="/mcp")
    return mcp


def _install_tool_call_analytics(mcp: FastApiMCP) -> None:
    """Emit an ``MCP_TOOL_CALL`` analytics event per tool invocation.

    fastapi-mcp forwards every tool call through the ASGI app, so each tool's
    own endpoint still runs its normal auth + logic — but nothing records that
    the call ARRIVED over MCP. That emitter used to live on the sync solve path
    (``SolveOrchestrator._log_analytics_solve``) and vanished with the
    async-only rewrite, pinning the MCP usage dashboard at zero.

    We wrap the private dispatch method (``_execute_api_tool``, the single choke
    point every tool call rides) rather than each endpoint, so all 30 tools are
    covered in one place. Best-effort and off the request's critical path: a
    failure here never affects the tool's result. Guarded on the method's
    presence so a fastapi-mcp upgrade degrades to "no MCP analytics", never a
    boot crash.
    """
    original = getattr(mcp, "_execute_api_tool", None)
    if original is None:  # pragma: no cover - defensive against a lib rename
        logger.warning("fastapi-mcp has no _execute_api_tool; MCP_TOOL_CALL analytics disabled")
        return

    import anyio

    async def _wrapped(*args: Any, **kwargs: Any) -> Any:
        # Signature-agnostic passthrough: fastapi-mcp calls its private dispatch with
        # keywords today, but a library upgrade switching conventions must degrade to
        # "no analytics" — never break every tool call on a TypeError in our wrapper.
        result = await original(*args, **kwargs)
        try:
            tool_name = kwargs.get("tool_name")
            if tool_name:
                http_request_info = kwargs.get("http_request_info")
                await anyio.to_thread.run_sync(_record_tool_call, tool_name, http_request_info)
        except Exception:  # analytics must never break a tool call
            logger.debug("Failed to record MCP_TOOL_CALL", exc_info=True)
        return result

    mcp._execute_api_tool = _wrapped  # type: ignore[method-assign]


def _record_tool_call(tool_name: str, http_request_info: Any) -> None:
    """Persist one ``MCP_TOOL_CALL`` event, resolving the caller from the Bearer.

    Runs in a worker thread (sync SQLAlchemy). Resolves ``(user, org)`` with the
    same credential resolver the HTTP API uses, off the forwarded Authorization
    header, so the event is attributed to the real principal. Anonymous or
    unauthenticated calls (no resolvable principal) are simply not counted.
    """
    from app.services.analytics_service import AnalyticsService
    from app.services.auth import resolve_principal
    from app.shared.db.session import SessionLocal

    headers = getattr(http_request_info, "headers", None) or {}
    # Starlette lower-cases header keys when building the dict.
    authorization = headers.get("authorization")
    if not authorization:
        return

    db = SessionLocal()
    try:
        user, org, _ = resolve_principal(db, authorization=authorization, commit_last_used=False)
        if user is None or org is None:
            return
        AnalyticsService(db).log_event(
            user_id=user.id,
            org_id=org.id,
            event_type=MCP_TOOL_CALL,
            ip_address=_client_ip(headers),
            metadata={"tool": tool_name},
        )
    finally:
        db.close()


def _client_ip(headers: dict[str, str]) -> str | None:
    """First hop of ``X-Forwarded-For`` (the real client behind the proxy)."""
    forwarded = headers.get("x-forwarded-for")
    if not forwarded:
        return None
    return forwarded.split(",")[0].strip() or None
