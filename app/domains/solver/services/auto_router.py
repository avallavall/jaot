"""Auto-routing decision logic — Phase 7.4 / D-11 / D-13 / INT-01.

Pure function :func:`select_solver` returning ``(solver_name, reason,
fallback_triggered)``. No DB access — Hexaly availability is determined by a
runtime probe of the Celery worker (``_probe_hexaly_worker`` in
``app.domains.solver.services.worker_health``).

Decision tree (post-Phase-7.4):

    1. All variables CONTINUOUS AND no quadratic terms anywhere -> ``"highs"``
       reason="lp_routed_to_highs", fallback_triggered=False
    2. Any quadratic term AND Hexaly worker available -> ``"hexaly"``
       reason="quadratic_routed_to_hexaly", fallback_triggered=False
    3. Any quadratic term AND Hexaly worker unavailable -> ``"scip"``
       reason="hexaly_unavailable_fallback", fallback_triggered=True
       (sync/async caller surfaces a `warning` field on the response — D-11)
    4. Otherwise (MIP / mixed) -> ``"scip"``
       reason="milp_routed_to_scip", fallback_triggered=False

Reason slugs are stable public contract (D-13): they travel on the solve
response, so renaming one is an API change. (The frontend does NOT translate
them — it shows a single "auto-routed" badge whenever a reason is present — so
the older note about updating locale strings no longer applies.)

The tree names its target solvers directly, which is what keeps those slugs
honest but also means the policy cannot read ``SolverCapabilities`` without
either lying in the slug or growing branches that never fire. The assumptions
underneath each branch — SCIP can do quadratics, HiGHS is always present — are
therefore pinned as invariants in ``tests/unit/domains/solver/services/
test_auto_router.py`` instead, so an adapter that changes what it supports
breaks the suite rather than quietly routing work to a solver that cannot do it.

**Where CBC and GLPK sit (owner asked, 2026-08-18).** They are substitutes, not
candidates. When the solver a branch prefers is installed — which is every
ordinary deployment — the decision above is unchanged to the byte, and neither
of them is ever chosen. They are reached only when the preferred solver is
absent from the image, and then in the order below.

Three reasons they are not promoted to first-class candidates:

- **Neither reports shadow prices or reduced costs.** A caller who asked for
  "auto" did not choose a solver, so routing them to one that silently drops the
  Sensitivity tab charges them for a decision they never made. SCIP and HiGHS
  both compute it.
- **GLPK is single-threaded and degrades badly on a hard model.** Measured on a
  60-lot burn-in plan (1,342 binaries, 3,558 rows): HiGHS 1.5 s, CBC 1.5 s,
  SCIP 12.2 s, and GLPK ran the full 60-second limit without ever finding a
  feasible plan. Auto must not be able to return nothing.
- **CBC is a genuine peer of the two on MILP**, and if it were only about speed
  it would belong in the tree. What is missing is a performance model: three
  measured instances is an anecdote, and the winner changed between them. A
  routing rule invented from that would be a guess wearing a slug.

The comparer is how a user answers "which solver for THIS model", with numbers,
and then names it explicitly. That is the honest division of labour, and it is
why this module does not try to guess it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domains.solver.adapters.base import HEXALY_SOLVER_NAME
from app.schemas.optimization import OptimizationProblem

if TYPE_CHECKING:  # pragma: no cover
    from app.domains.solver.services.classify import ProblemClass
    from app.domains.solver.services.expression_parser import ExpressionParser

logger = logging.getLogger(__name__)


# Reason slugs (D-13). Stable public contract — frontend locale strings key
# off these.
AUTO_REASON_LP = "lp_routed_to_highs"
AUTO_REASON_QUADRATIC = "quadratic_routed_to_hexaly"
AUTO_REASON_FALLBACK = "hexaly_unavailable_fallback"
AUTO_REASON_MIP = "milp_routed_to_scip"
#: The solver this problem class prefers is not installed on this server, so
#: auto used the best substitute that can express the model. ``solver_used`` on
#: the response says which one; this slug says why it is not the usual one.
AUTO_REASON_SUBSTITUTED = "preferred_solver_not_installed"

#: Who auto falls back to, in order, when the preferred solver is missing.
#: Ordered by what the caller gets back, not by speed: SCIP and HiGHS compute
#: shadow prices and reduced costs, CBC and GLPK do not, and GLPK is
#: single-threaded. A solver that cannot express the problem's class is dropped
#: from this list before any of it is consulted, so quadratics never reach CBC
#: or GLPK whatever the order says.
_SUBSTITUTES: tuple[str, ...] = ("scip", "highs", "cbc", "glpk")


def select_solver(
    problem: OptimizationProblem,
    parser: ExpressionParser | None = None,
) -> tuple[str, str, bool]:
    """Select the best solver per the Phase 7.4 decision tree.

    Args:
        problem: The optimization problem to classify.
        parser: Optional :class:`ExpressionParser` override. Defaults to a
            fresh instance (lazy-imported to keep ``auto_router`` import
            cheap).

    Returns:
        Tuple ``(solver_name, reason, fallback_triggered)``:
          - ``solver_name``: one of ``"highs"``, ``"hexaly"``, ``"scip"``.
          - ``reason``: one of the four :data:`AUTO_REASON_*` constants.
          - ``fallback_triggered``: True iff Hexaly was the preferred choice
            but the worker was unavailable; the caller MUST surface a
            ``warning`` field on the solve response per D-11.

    Pure function: deterministic given (problem, worker-availability snapshot).
    No DB access. No multi-tenancy concerns (no org-scoped reads).
    """
    if parser is None:
        from app.domains.solver.services.expression_parser import (  # noqa: PLC0415
            ExpressionParser,
        )

        parser = ExpressionParser()

    # Single source of truth for the problem class (shared with ModelStatsService).
    # The routing below is exactly the legacy two-boolean tree: ``cls == LP`` is the
    # old ``pure_lp and not has_quadratic``, and ``cls in QUADRATIC_CLASSES`` is the
    # old ``has_quadratic`` — so routing + reason slugs are unchanged.
    from app.domains.solver.services.classify import (  # noqa: PLC0415
        QUADRATIC_CLASSES,
        ProblemClass,
        classify,
    )

    cls = classify(problem, parser)
    has_quadratic = cls in QUADRATIC_CLASSES

    # 1. LP -> HiGHS
    if cls == ProblemClass.LP:
        return _prefer("highs", AUTO_REASON_LP, cls)

    # 2 + 3. Quadratic — check worker, fall back to SCIP if down (D-11).
    # Probe the source-level helper directly so a single mock target covers
    # both this routing decision AND the post-routing availability gate
    # (availability_gate.ensure_hexaly_worker_or_503 calls _probe_hexaly_worker
    # too; tests that mock at one layer but not the other surface 503 in a
    # 422-expecting test).
    if has_quadratic:
        from app.domains.solver.services.worker_health import (  # noqa: PLC0415
            _probe_hexaly_worker,
        )

        healthy, probe_msg = _probe_hexaly_worker()
        if healthy:
            return (HEXALY_SOLVER_NAME, AUTO_REASON_QUADRATIC, False)
        logger.warning(
            "auto_router: Hexaly worker unavailable (%s), falling back to SCIP "
            "for quadratic problem (D-11 explicit fallback).",
            probe_msg or "no diagnostic message",
        )
        # The Hexaly fallback keeps its own slug and its own flag: the caller
        # gates a 503 probe on that flag, and the warning it raises is about
        # solution quality, not about a missing install. Substituting for a
        # missing SCIP on top of it is still allowed, and reports the same
        # "Hexaly fell back" reason, because that is the fact the user needs.
        substitute, _reason, _ = _prefer("scip", AUTO_REASON_FALLBACK, cls)
        return (substitute, AUTO_REASON_FALLBACK, True)

    # 4. MIP / mixed default
    return _prefer("scip", AUTO_REASON_MIP, cls)


def _prefer(
    preferred: str,
    reason: str,
    problem_class: ProblemClass,
) -> tuple[str, str, bool]:
    """``preferred`` when this server has it, otherwise the best substitute.

    On any ordinary deployment the preferred solver is installed and this
    returns exactly what the decision tree above always returned, with its
    historic slug. The substitution path exists because an image can be built
    without a solver — the test image ships without CBC and GLPK, and the Hexaly
    worker is a different build entirely — and until now auto would name a
    solver that is not there and let the caller fail on it, having asked the
    user for no choice at all.

    A substitute must be able to express the problem's class. That question is
    answered by the comparer's own ``capability_gap``, so the two surfaces
    cannot disagree about which solver can run which model.

    When nothing at all can run it, the preferred name is returned unchanged:
    the caller already turns an unavailable solver into its usual error, and
    inventing a different failure here would only move where it is reported.
    """
    if _can_run(preferred, problem_class):
        return (preferred, reason, False)

    for candidate in _SUBSTITUTES:
        if candidate != preferred and _can_run(candidate, problem_class):
            logger.warning(
                "auto_router: %s is not installed on this server; %s substituted for a %s.",
                preferred,
                candidate,
                problem_class.value,
            )
            return (candidate, AUTO_REASON_SUBSTITUTED, False)

    logger.error(
        "auto_router: no installed solver can run a %s; reporting %s so the caller "
        "raises its usual unavailable error.",
        problem_class.value,
        preferred,
    )
    return (preferred, reason, False)


def _can_run(name: str, problem_class: ProblemClass) -> bool:
    """Is ``name`` installed here, and can it express this class?

    Never raises: the registry raises for a name it does not know and for one
    whose adapter reports itself unavailable, and both mean the same thing to a
    routing decision.
    """
    from app.domains.solver.adapters import registry  # noqa: PLC0415
    from app.domains.solver.services.comparison_service import (  # noqa: PLC0415
        capability_gap,
    )

    try:
        adapter = registry.get(name)
    except Exception:
        return False
    return capability_gap(adapter.capabilities, problem_class) is None


def warning_for(reason: str | None, solver_used: str | None) -> str | None:
    """The sentence a caller should surface for an auto-routing decision.

    Written once, here, next to the slugs. It used to be a literal at each call
    site naming Hexaly and SCIP, which was true of the only case that existed
    and would have quietly lied about any other.
    """
    if reason == AUTO_REASON_FALLBACK:
        return (
            f"Hexaly temporarily unavailable; solved with "
            f"{(solver_used or 'another solver').upper()} "
            f"(quadratic quality may differ)"
        )
    if reason == AUTO_REASON_SUBSTITUTED:
        return (
            f"The usual solver for this kind of model is not installed on this server; "
            f"solved with {(solver_used or 'another solver').upper()} instead"
        )
    return None


__all__ = [
    "AUTO_REASON_FALLBACK",
    "AUTO_REASON_LP",
    "AUTO_REASON_MIP",
    "AUTO_REASON_QUADRATIC",
    "AUTO_REASON_SUBSTITUTED",
    "select_solver",
    "warning_for",
]
