"""JModel DSL endpoints — compile a declarative source to the flat problem (P5).

Thin route layer: it lives in ``app.api`` (not ``app.domains.dsl``) so it can import
both the pure DSL compiler and any cross-cutting service without breaching the
``domains-independent`` import-linter contract. The compiler itself imports only
``app.schemas``.

``POST /dsl/compile`` is gated behind the ``JAOT_DSL`` flag (404 when off).
``GET /dsl/status`` is ungated so the SPA can decide whether to surface the lens.

Both handlers are deliberately **sync** (``def``): FastAPI runs them in its thread
pool, so a CPU-bound compile of a large model never blocks the event loop (the editor
calls this endpoint on every debounced keystroke).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import CurrentOrg, CurrentUser, DBSession, RequestLocale
from app.api.v2.deps.dsl_feature_gate import dsl_enabled, dsl_feature_gate
from app.domains.dsl import (
    JModelData,
    JModelError,
    compile_jmodel,
    inspect_declarations,
    latexify,
)
from app.schemas.dsl import (
    DSL_GENERATE_MEDIA_TYPES,
    DSLCompileError,
    DSLCompileRequest,
    DSLCompileResponse,
    DSLDegroundRequest,
    DSLDegroundResponse,
    DSLGenerateRequest,
    DSLGenerateResponse,
    DSLInspectRequest,
    DSLInspectResponse,
    DSLLatexLine,
    DSLLatexModel,
    DSLLatexRequest,
    DSLLatexResponse,
    DSLParamDecl,
    DSLSetDecl,
    DSLStatusResponse,
)
from app.services import model_project_service as project_svc
from app.services.jmodel_deground import deground_problem, deground_problem_split
from app.services.jmodel_generate import generate_jmodel
from app.services.llm.anthropic_client import get_anthropic_client
from app.services.llm.byok import resolve_anthropic_client
from app.services.llm.cost_tracking import (
    is_llm_budget_exceeded,
    record_standalone_llm_spend,
)
from app.services.llm.errors import handle_anthropic_failure
from app.services.llm.formulation_service import select_model
from app.services.llm.moderation import moderate_message
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.core.rate_limiter import check_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dsl", tags=["dsl"])


@router.get("/status", operation_id="dsl_status")
def dsl_status(db: DBSession, _user: CurrentUser) -> DSLStatusResponse:
    """Report whether the JModel DSL feature is enabled on this instance."""
    return DSLStatusResponse(enabled=dsl_enabled(db))


@router.post(
    "/compile",
    operation_id="dsl_compile",
    dependencies=[Depends(dsl_feature_gate)],
)
def dsl_compile(body: DSLCompileRequest, db: DBSession, org: CurrentOrg) -> DSLCompileResponse:
    """Compile JModel source into a flat optimization problem.

    ``dataset_id`` (optional) names an org-owned dataset whose set members / param
    values fill a declaration-only source (§8 Scenarios). Returns ``ok=false`` with
    a structured error on any lex/parse/dataset/grounding failure, so the editor can
    surface the message and position without a 4xx round-trip — including a dataset
    deleted from under an open editor.
    """
    try:
        data = None
        if body.dataset_id:
            dataset = project_svc.get_dataset_or_404(db, body.dataset_id, org.id)
            if dataset is None:
                return DSLCompileResponse(
                    ok=False,
                    error=DSLCompileError(
                        message="dataset not found — it may have been deleted",
                        position=None,
                    ),
                )
            data = JModelData.from_json(dataset.data_json)
        problem = compile_jmodel(body.source, data=data)
    except JModelError as exc:
        return DSLCompileResponse(
            ok=False,
            error=DSLCompileError(message=exc.message, position=exc.position),
        )
    except Exception:
        # The compiler contract is "JModelError or a problem" — anything else is a
        # compiler bug. Surface it as a structured failure (never a 500 mid-keystroke)
        # and log it loudly for us.
        logger.exception("JModel compiler crashed on user source")
        return DSLCompileResponse(
            ok=False,
            error=DSLCompileError(message="internal compiler error", position=None),
        )
    return DSLCompileResponse(ok=True, problem=problem)


@router.post(
    "/inspect",
    operation_id="dsl_inspect",
    dependencies=[Depends(dsl_feature_gate)],
)
def dsl_inspect(body: DSLInspectRequest, _user: CurrentUser) -> DSLInspectResponse:
    """List a source's data-facing declarations — parse-only, never grounded (S2a).

    Powers the dataset editor's "skeleton from the model" button and the live
    dataset↔model validation (S5): it must succeed for declaration-only sources
    AND for sources whose data is missing, states in which ``/dsl/compile`` errors.
    Same structured-error contract as compile (no 4xx mid-keystroke).
    """
    try:
        decls = inspect_declarations(body.source)
    except JModelError as exc:
        return DSLInspectResponse(
            ok=False,
            error=DSLCompileError(message=exc.message, position=exc.position),
        )
    except Exception:
        logger.exception("JModel inspector crashed on user source")
        return DSLInspectResponse(
            ok=False,
            error=DSLCompileError(message="internal compiler error", position=None),
        )
    return DSLInspectResponse(
        ok=True,
        sets=[DSLSetDecl(name=s.name, has_inline_values=s.has_inline_values) for s in decls.sets],
        params=[
            DSLParamDecl(
                name=p.name,
                index_sets=list(p.index_sets),
                arity=p.arity,
                has_inline_values=p.has_inline_values,
            )
            for p in decls.params
        ],
    )


@router.post(
    "/latex",
    operation_id="dsl_latex",
    dependencies=[Depends(dsl_feature_gate)],
)
def dsl_latex(body: DSLLatexRequest, _user: CurrentUser) -> DSLLatexResponse:
    """Pretty-print a source as symbolic math for the JModel split-pane (B1).

    Parse-only: it renders the indexed objective / ∀-quantified constraint families /
    variable domains from the AST BEFORE grounding, so the sum & quantifier structure
    survives (grounding would flatten it to thousands of scalar rows). Needs no data,
    so it succeeds for declaration-only sources — states in which ``/dsl/compile``
    errors. Same structured-error contract as compile (no 4xx mid-keystroke).
    """
    try:
        rendered = latexify(body.source)
    except JModelError as exc:
        return DSLLatexResponse(
            ok=False,
            error=DSLCompileError(message=exc.message, position=exc.position),
        )
    except Exception:
        logger.exception("JModel LaTeX renderer crashed on user source")
        return DSLLatexResponse(
            ok=False,
            error=DSLCompileError(message="internal compiler error", position=None),
        )
    return DSLLatexResponse(
        ok=True,
        model=DSLLatexModel(
            objective=(
                DSLLatexLine(latex=rendered.objective.latex, label=rendered.objective.label)
                if rendered.objective
                else None
            ),
            constraints=[
                DSLLatexLine(latex=line.latex, label=line.label) for line in rendered.constraints
            ],
            variables=[
                DSLLatexLine(latex=line.latex, label=line.label) for line in rendered.variables
            ],
        ),
    )


@router.post(
    "/deground",
    operation_id="dsl_deground",
    dependencies=[Depends(dsl_feature_gate)],
)
def dsl_deground(body: DSLDegroundRequest, _user: CurrentUser) -> DSLDegroundResponse:
    """Reconstruct a compact JModel draft from a flat problem (B2, phase 1).

    The inverse of compile: a model built on the canvas or imported (MPS/LP/CIP) has
    no JModel source, so this recovers one — variable families over sets, ``sum``
    objectives and ∀-quantified constraint families — so it can be read, edited and
    shown as math (B1) in compact form. Heuristic, so honest: it returns ``source``
    only when the draft VERIFIABLY round-trips to an equivalent problem, and ``null``
    (a graceful decline, never a fake) otherwise.
    """
    source: str | None = None
    dataset: dict | None = None
    try:
        if body.allow_dataset:
            # The elegant form: the source is the GENERAL formulation and the data
            # goes where data belongs — a dataset the caller stores and selects.
            draft = deground_problem_split(body.problem)
            if draft is not None:
                source, dataset = draft.source, draft.dataset
        else:
            source = deground_problem(body.problem)
    except Exception:
        # The service is contracted to return draft-or-None; anything else is a bug.
        # Decline gracefully (never a 500) and log it for us.
        logger.exception("JModel de-grounder crashed on a flat problem")
        source, dataset = None, None
    return DSLDegroundResponse(source=source, dataset=dataset)


@router.post(
    "/generate",
    operation_id="dsl_generate",
    dependencies=[Depends(dsl_feature_gate)],
)
async def dsl_generate(
    body: DSLGenerateRequest,
    request: Request,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    locale: RequestLocale,
) -> DSLGenerateResponse:
    """Generate a JModel source from a description and/or screenshots/PDFs (B3).

    Turns JModel's determinism into a self-correcting loop: Claude proposes a source,
    the compiler validates it, and any structured error is fed back for a retry. The
    response's ``ok`` is true ONLY when the returned source verifiably compiles; when
    every retry fails it still returns the best-effort draft plus the last compile
    error, so the editor lands on an editable start rather than nothing.

    Same guardrails as the chat assistant: BYOK-first (an org key runs on the org's own
    account and skips the platform budget), monthly-budget pause, LLM rate limit, and a
    content-moderation pre-check on the description.
    """
    # At least one of description / attachments must carry the problem.
    if not body.description.strip() and not body.attachments:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide a description or attach a screenshot/PDF of the problem.",
        )

    # Validate attachment media types (the schema bounds count + size; the enum lives here
    # next to the vision block builder so both stay in sync).
    for att in body.attachments:
        if att.media_type not in DSL_GENERATE_MEDIA_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Unsupported attachment type '{att.media_type}'. "
                    "Allowed: PNG, JPEG, GIF, WebP images or PDF."
                ),
            )

    # BYOK: when the org has its own Anthropic key, the call runs on their account —
    # so the platform budget guardrail below is skipped and the spend is never booked
    # against the platform budget.
    byok_client, is_byok = resolve_anthropic_client(org)

    if not is_byok and is_llm_budget_exceeded(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "feature_not_available",
                "message": (
                    "The AI assistant is taking a short break — the platform's monthly "
                    "AI budget has been reached. It will be back at the start of next month."
                ),
                "reason": "llm_monthly_budget_exhausted",
            },
        )

    allowed, rate_info = check_rate_limit(
        f"llm:{org.id}",
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_MINUTE"),
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_DAY"),
    )
    if not allowed:
        retry_after = rate_info.get("retry_after") if isinstance(rate_info, dict) else None
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        raise HTTPException(status_code=429, detail=rate_info, headers=headers)

    if body.description.strip():
        is_allowed, rejection_msg = moderate_message(body.description)
        if not is_allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=rejection_msg,
            )

    # Resolve the client: BYOK when present, else the shared platform client. A missing
    # platform key is a friendly "feature not configured", never a 500.
    try:
        client = byok_client or get_anthropic_client(db=db)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "feature_not_available",
                "message": "The AI assistant is not configured on this instance.",
                "reason": "llm_not_configured",
            },
        ) from None

    # Default model (Sonnet-tier): fast + cheap, and the compile-retry loop backstops
    # correctness, so reasoning is unnecessary for a compact DSL.
    # Honour the caller's choice instead of pinning the default: this endpoint is one of
    # the LLM surfaces the advanced-model toggle covers. (The second value select_model
    # returns is the thinking flag, which generate_jmodel does not take — the toggle
    # switches the model here, not the thinking budget.)
    model, _ = select_model(use_advanced=body.use_advanced_model, db=db)
    max_tokens = PSS.get_int(db, "LLM_MAX_TOKENS")

    request_id = getattr(request.state, "request_id", None) or ""
    try:
        outcome = await generate_jmodel(
            client=client,
            model=model,
            max_tokens=max_tokens,
            description=body.description,
            attachments=body.attachments,
            current_source=body.current_source,
            locale=locale,
        )
    except Exception as exc:
        # Anthropic transport / API failure. handle_anthropic_failure logs + classifies;
        # never leak the raw exception detail to the client.
        error_event = handle_anthropic_failure(
            exc, logger=logger, context="dsl generate", request_id=request_id
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "ai_error",
                "message": "The AI service could not complete the request. Please try again.",
                "reason": error_event["code"].value,
            },
        ) from None

    # Book the spend against the monthly platform budget — only for platform-key runs
    # (BYOK spend is on the org's own account). Best-effort; never fails the response.
    if not is_byok:
        record_standalone_llm_spend(
            db,
            org_id=org.id,
            user_id=user.id,
            model=model,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            summary=(
                f"JModel AI generation ({outcome.attempts} attempt(s), "
                f"{'compiled' if outcome.ok else 'did not compile'})"
            ),
        )

    error = None
    if not outcome.ok and outcome.error_message:
        error = DSLCompileError(message=outcome.error_message, position=outcome.error_position)

    return DSLGenerateResponse(
        ok=outcome.ok,
        source=outcome.source,
        error=error,
        attempts=outcome.attempts,
    )
