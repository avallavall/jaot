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

from fastapi import APIRouter, Depends

from app.api.deps import CurrentOrg, CurrentUser, DBSession
from app.api.v2.deps.dsl_feature_gate import dsl_enabled, dsl_feature_gate
from app.domains.dsl import (
    JModelData,
    JModelError,
    compile_jmodel,
    inspect_declarations,
    latexify,
)
from app.schemas.dsl import (
    DSLCompileError,
    DSLCompileRequest,
    DSLCompileResponse,
    DSLDegroundRequest,
    DSLDegroundResponse,
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
from app.services.jmodel_deground import deground_problem

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
    try:
        source = deground_problem(body.problem)
    except Exception:
        # The service is contracted to return source-or-None; anything else is a bug.
        # Decline gracefully (never a 500) and log it for us.
        logger.exception("JModel de-grounder crashed on a flat problem")
        source = None
    return DSLDegroundResponse(source=source)
