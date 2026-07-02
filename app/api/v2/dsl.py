"""JModel DSL endpoints — compile a declarative source to the flat problem (P5).

Thin route layer: it lives in ``app.api`` (not ``app.domains.dsl``) so it can import
both the pure DSL compiler and any cross-cutting service without breaching the
``domains-independent`` import-linter contract. The compiler itself imports only
``app.schemas``.

``POST /dsl/compile`` is gated behind the ``JAOT_DSL`` flag (404 when off).
``GET /dsl/status`` is ungated so the SPA can decide whether to surface the lens.
"""

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DBSession
from app.api.v2.deps.dsl_feature_gate import dsl_enabled, dsl_feature_gate
from app.domains.dsl import JModelError, compile_jmodel
from app.schemas.dsl import (
    DSLCompileError,
    DSLCompileRequest,
    DSLCompileResponse,
    DSLStatusResponse,
)

router = APIRouter(prefix="/dsl", tags=["dsl"])


@router.get("/status", operation_id="dsl_status")
async def dsl_status(db: DBSession, _user: CurrentUser) -> DSLStatusResponse:
    """Report whether the JModel DSL feature is enabled on this instance."""
    return DSLStatusResponse(enabled=dsl_enabled(db))


@router.post(
    "/compile",
    operation_id="dsl_compile",
    dependencies=[Depends(dsl_feature_gate)],
)
async def dsl_compile(body: DSLCompileRequest, _user: CurrentUser) -> DSLCompileResponse:
    """Compile JModel source into a flat optimization problem.

    Returns ``ok=false`` with a structured error on any lex/parse/grounding failure,
    so the editor can surface the message and position without a 4xx round-trip.
    """
    try:
        problem = compile_jmodel(body.source)
    except JModelError as exc:
        return DSLCompileResponse(
            ok=False,
            error=DSLCompileError(message=exc.message, position=exc.position),
        )
    return DSLCompileResponse(ok=True, problem=problem)
