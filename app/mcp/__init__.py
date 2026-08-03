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
from app.shared.utils.request_helpers import get_client_ip_from_headers

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
    _fix_server_identity(mcp, app)
    mcp.mount_http(mount_path="/mcp")
    _force_stateless_http(mcp)
    return mcp


def _force_stateless_http(mcp: FastApiMCP) -> None:
    """Serve MCP over HTTP without server-side sessions — required under multiple workers.

    fastapi-mcp 0.4.0 hardcodes ``stateless=False`` when it builds the SDK's
    ``StreamableHTTPSessionManager``, which keeps every session in a dict owned
    by ONE worker process. Production runs several uvicorn workers, so any
    request whose ``mcp-session-id`` lands on a different worker than the one
    that answered ``initialize`` gets 404 "Session not found". Measured against
    production with 4 workers: 20/20 back-to-back calls succeed (keep-alive pins
    the connection to one worker), while calls separated by realistic pauses
    fail 3 out of 4 — exactly the odds of landing on another worker. A real
    client thinks between calls, so this broke every real client.

    The SDK supports ``stateless=True`` for precisely this deployment shape: a
    fresh transport per request, no session id issued, and a client that still
    sends a cached ``mcp-session-id`` is accepted (the header is ignored), so
    the rollout cuts nobody off. Nothing we serve needs sessions: no event
    store, no sampling, and JSON response mode already drops out-of-request
    notifications.

    The manager is created lazily on the first request deep inside fastapi-mcp,
    so we wrap the transport's startup hook and flip the flag the moment the
    manager exists — dispatch reads it per request, and every request passes
    through this hook first. Guarded like the rest of this module: if a library
    upgrade renames the attributes, degrade to stateful-as-shipped with a
    warning, never a boot crash.
    """
    transport = getattr(mcp, "_http_transport", None)
    ensure_started = getattr(transport, "_ensure_session_manager_started", None)
    if transport is None or ensure_started is None:  # pragma: no cover - lib change
        logger.warning(
            "fastapi-mcp exposes no HTTP transport startup hook; "
            "MCP stays session-bound (single-worker only)"
        )
        return

    async def _ensure_started_stateless() -> None:
        await ensure_started()
        manager = getattr(transport, "_session_manager", None)
        if manager is None:  # pragma: no cover - defensive against a lib change
            logger.warning("MCP session manager missing after start; MCP stays session-bound")
            return
        if not manager.stateless:
            manager.stateless = True
            logger.info("MCP HTTP transport forced stateless (multi-worker safe)")

    transport._ensure_session_manager_started = _ensure_started_stateless  # type: ignore[method-assign]


def _fix_server_identity(mcp: FastApiMCP, app: FastAPI) -> None:
    """Put the version in ``version`` and the description where clients read it.

    The low-level server takes ``Server(name, version, instructions)``, but
    fastapi-mcp 0.4.0 constructs it as ``Server(self.name, self.description)`` —
    so the description lands in the version slot. Measured against production:
    every client completing the handshake was told JAOT's version was a 722-char
    paragraph, and ``instructions`` — the field a model actually reads to learn
    what the server is for — arrived empty.

    Best-effort and guarded: a library upgrade that fixes this upstream, or
    renames the attribute, must degrade to "identity as the library set it",
    never a boot crash.
    """
    server = getattr(mcp, "server", None)
    if server is None:  # pragma: no cover - defensive against a lib change
        logger.warning("fastapi-mcp exposes no .server; MCP serverInfo left as-is")
        return
    if getattr(server, "instructions", None) is None:
        server.instructions = mcp.description
    server.version = app.version


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
    """The caller's address, by the same trust order as the rest of the platform.

    This used to read the first hop of ``X-Forwarded-For`` directly — the entry a
    caller chooses, since proxies append — so an MCP client could put any address
    in its own audit-log row.
    """
    return get_client_ip_from_headers(headers)
