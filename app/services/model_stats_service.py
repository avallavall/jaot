"""ModelStatsService — structural statistics + an auditable health score.

Computes a :class:`ModelStats` from a solver-agnostic ``OptimizationProblem`` in a
single parse pass (O(nnz)), reusing the solver domain's ``ExpressionParser`` and the
shared ``classify()``. Used by the Analyze surface (``GET /projects/{id}/stats``),
frozen onto each committed version, and the natural home to unify the ad-hoc counts
scattered across import-preview / validate-credits (a follow-up).

Pure + defensive: a half-built or invalid draft never raises — it degrades to a
best-effort result with warnings, so the live-stats panel is always renderable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from typing import Any

from app.domains.solver.services.classify import classify
from app.domains.solver.services.expression_parser import ExpressionParser, ParseError
from app.schemas.model_stats import (
    BoundProfile,
    CoefConditioning,
    HealthDeduction,
    ModelHealth,
    ModelStats,
)
from app.schemas.optimization import OptimizationProblem, VariableType

logger = logging.getLogger(__name__)

# Coefficient range-ratio tiers (numerical conditioning).
_TIER_MILD = 1e6
_TIER_POOR = 1e9
_TIER_SEVERE = 1e12

_CACHE_TTL_SECONDS = 120


def _content_hash(model_json: dict[str, Any] | None) -> str:
    canonical = json.dumps(model_json or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _band(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def compute(problem: OptimizationProblem, *, content_hash: str | None = None) -> ModelStats:
    """Compute structural statistics + health for a validated ``OptimizationProblem``."""
    parser = ExpressionParser()
    # A SET on purpose — the parser adopts it without copying (per-constraint
    # set() rebuilds made stats on 100k-constraint models take minutes).
    known = {v.name for v in problem.variables}
    warnings: list[str] = []
    hard_error = False

    # --- Variables + bounds ---
    var_continuous = var_integer = var_binary = 0
    free = boxed = one_sided = binary = integers_missing_bounds = 0
    lb_gt_ub = 0
    nonfinite_bound = 0
    for v in problem.variables:
        if v.type == VariableType.BINARY:
            var_binary += 1
            binary += 1
        elif v.type == VariableType.INTEGER:
            var_integer += 1
        else:
            var_continuous += 1

        lb, ub = v.lower_bound, v.upper_bound
        if (lb is not None and not math.isfinite(lb)) or (ub is not None and not math.isfinite(ub)):
            nonfinite_bound += 1
        if lb is not None and ub is not None and lb > ub:
            lb_gt_ub += 1

        if v.type != VariableType.BINARY:
            if lb is None and ub is None:
                free += 1
            elif lb is not None and ub is not None:
                boxed += 1
            else:
                one_sided += 1
        if v.type == VariableType.INTEGER and (lb is None or ub is None):
            integers_missing_bounds += 1

    var_total = len(problem.variables)
    has_int = var_integer + var_binary

    # --- Objective ---
    obj_terms = 0
    obj_quadratic = False
    obj_coef: dict[str, float] = {}
    used_vars: set[str] = set()
    coefs: list[float] = []
    nonfinite_coef = False
    try:
        parsed_obj = parser.parse_expression(problem.objective.expression, known_variables=known)
        obj_terms = len(parsed_obj.terms)
        obj_quadratic = not parsed_obj.is_linear()
        for t in parsed_obj.terms:
            if not math.isfinite(t.coefficient):
                nonfinite_coef = True
                continue
            coefs.append(abs(t.coefficient))
            used_vars.update(t.variables)
            if len(t.variables) == 1:
                obj_coef[t.variables[0]] = t.coefficient
        if obj_terms == 0:
            warnings.append("Objective references no variables — this is a feasibility-only model.")
    except ParseError:
        warnings.append("Objective expression could not be parsed.")

    # --- Constraints ---
    by_op: dict[str, int] = {}
    nonzeros = 0
    constant_infeasible = 0
    seen_names: set[str] = set()
    dup_names = 0
    missing_names = 0
    # One aggregate warning for unparseable rows (with a small name sample) instead of
    # one per row — a large broken import must not balloon stats_json with 10k+ strings.
    unparseable = 0
    unparseable_sample: list[str] = []
    # Which variables some row already caps, and in which direction. Bounding the
    # decision variables through capacity rows rather than through their own
    # bounds is the normal way to write a model, so the unboundedness flag below
    # cannot be read off the bounds alone.
    capped_up: set[str] = set()
    capped_down: set[str] = set()
    for c in problem.constraints:
        if c.name is None or c.name == "":
            missing_names += 1
        else:
            if c.name in seen_names:
                dup_names += 1
            seen_names.add(c.name)
        try:
            parsed = parser.parse_constraint(c.expression, known_variables=known)
        except ParseError:
            unparseable += 1
            if len(unparseable_sample) < 5:
                unparseable_sample.append(c.name or "?")
            continue
        by_op[parsed.operator] = by_op.get(parsed.operator, 0) + 1
        var_terms = [t for t in parsed.lhs.terms if t.variables]
        nonzeros += len(var_terms)
        for t in var_terms:
            if not math.isfinite(t.coefficient):
                nonfinite_coef = True
                continue
            coefs.append(abs(t.coefficient))
            used_vars.update(t.variables)
            # `a*x <= rhs` caps x from above when a > 0 and from below when a < 0;
            # `>=` is the mirror; `==` caps both ways. Single-variable terms only —
            # a bilinear term says nothing about either factor on its own.
            if len(t.variables) == 1:
                name, a = t.variables[0], t.coefficient
                op = parsed.operator
                if op == "==":
                    capped_up.add(name)
                    capped_down.add(name)
                elif op == "<=":
                    (capped_up if a > 0 else capped_down).add(name)
                elif op == ">=":
                    (capped_down if a > 0 else capped_up).add(name)
        if math.isfinite(parsed.rhs) and parsed.rhs != 0.0:
            coefs.append(abs(parsed.rhs))
        # A row with no variable terms is `0 <op> rhs` — possibly trivially infeasible.
        if not var_terms and math.isfinite(parsed.rhs):
            op, rhs = parsed.operator, parsed.rhs
            if (op == "<=" and rhs < 0) or (op == ">=" and rhs > 0) or (op == "==" and rhs != 0):
                constant_infeasible += 1

    constraint_total = len(problem.constraints)
    density = nonzeros / (constraint_total * var_total) if (constraint_total and var_total) else 0.0
    integrality_ratio = (has_int / var_total) if var_total else 0.0

    # --- Conditioning ---
    nonzero_coefs = [c for c in coefs if c > 0]
    if nonzero_coefs:
        min_abs: float | None = min(nonzero_coefs)
        max_abs: float | None = max(nonzero_coefs)
        ratio: float | None = (max_abs / min_abs) if min_abs and min_abs > 0 else None
    else:
        min_abs = max_abs = ratio = None
    if ratio is None or ratio < _TIER_MILD:
        tier = "ok"
    elif ratio < _TIER_POOR:
        tier = "mild"
    elif ratio < _TIER_SEVERE:
        tier = "poor"
    else:
        tier = "severe"

    # --- Disconnected variables (in no constraint and zero objective coefficient) ---
    disconnected = sum(1 for v in problem.variables if v.name not in used_vars)

    # --- Unboundedness risk: nothing at all stops this variable improving ---
    # This used to look only at the declared bounds, and so fired on almost every
    # legitimate model: capping decision variables with capacity rows instead of
    # with their own upper bounds is the ordinary way to write one. Measured on
    # `max 3x+2y ; x+y<=4 ; x+3y<=6 ; x<=3` — a model JAOT itself solves to a
    # finite 11 — it reported two variables at risk, warned "may be UNBOUNDED"
    # and docked the health score from A to B, live in the studio while you type.
    #
    # A row that caps the variable in the improving direction now clears it. That
    # trades some recall for precision on purpose: a warning that cries wolf on
    # every model is one nobody reads, and a genuinely unbounded model is named as
    # such by the solver the moment it runs.
    sense = getattr(problem.objective.sense, "value", problem.objective.sense)
    unbounded_risk = 0
    for v in problem.variables:
        c = obj_coef.get(v.name)
        if not c:
            continue
        if v.type == VariableType.BINARY:
            continue
        improves_up = (c > 0) if sense == "maximize" else (c < 0)
        if improves_up:
            if v.upper_bound is None and v.name not in capped_up:
                unbounded_risk += 1
        elif v.lower_bound is None and v.name not in capped_down:
            unbounded_risk += 1

    # --- Warnings (human-readable) ---
    if unparseable:
        sample = ", ".join(f"'{n}'" for n in unparseable_sample)
        suffix = ", …" if unparseable > len(unparseable_sample) else ""
        warnings.append(f"{unparseable} constraint(s) could not be parsed ({sample}{suffix}).")
    if lb_gt_ub:
        hard_error = True
        warnings.append(f"{lb_gt_ub} variable(s) have lower_bound > upper_bound (infeasible).")
    if constant_infeasible:
        hard_error = True
        warnings.append(f"{constant_infeasible} constraint(s) are trivially infeasible.")
    if nonfinite_coef or nonfinite_bound:
        hard_error = True
        warnings.append("Model contains non-finite (NaN/Inf) coefficients or bounds.")
    if integers_missing_bounds:
        warnings.append(
            f"{integers_missing_bounds} integer variable(s) are missing a bound "
            "(weak branch-and-bound)."
        )
    if unbounded_risk:
        warnings.append(
            f"{unbounded_risk} variable(s) are unbounded in the optimizing direction "
            "— the model may be UNBOUNDED."
        )
    if disconnected:
        warnings.append(f"{disconnected} variable(s) appear in no constraint or objective.")
    if tier != "ok":
        warnings.append(
            f"Coefficient magnitudes span ~{ratio:.0e} ({tier} numerical conditioning)."
        )
    if dup_names:
        warnings.append(f"{dup_names} duplicate constraint name(s).")

    # --- Problem class (shared classify) ---
    try:
        problem_class: str | None = classify(problem, parser).value
    except ParseError:
        problem_class = None

    # --- Health score (transparent; hard errors cap at band F) ---
    deductions: list[HealthDeduction] = []
    if unbounded_risk:
        deductions.append(
            HealthDeduction(
                code="unboundedness_risk", points=15, detail="Unbounded in optimizing direction"
            )
        )
    if integers_missing_bounds and (var_integer + var_binary):
        frac = integers_missing_bounds / (var_integer + var_binary)
        deductions.append(
            HealthDeduction(
                code="integers_missing_bounds",
                points=round(10 * frac),
                detail="Integers without bounds",
            )
        )
    if tier == "mild":
        deductions.append(
            HealthDeduction(code="conditioning_mild", points=5, detail="Coefficient range >1e6")
        )
    elif tier == "poor":
        deductions.append(
            HealthDeduction(code="conditioning_poor", points=15, detail="Coefficient range >1e9")
        )
    elif tier == "severe":
        deductions.append(
            HealthDeduction(code="conditioning_severe", points=25, detail="Coefficient range >1e12")
        )
    if disconnected and var_total:
        deductions.append(
            HealthDeduction(
                code="disconnected_vars",
                points=round(5 * disconnected / var_total),
                detail="Unused variables",
            )
        )
    if obj_terms == 0:
        deductions.append(
            HealthDeduction(code="empty_objective", points=10, detail="No objective terms")
        )
    name_issues = dup_names + missing_names
    if name_issues:
        deductions.append(
            HealthDeduction(
                code="name_issues",
                points=min(10, 2 * name_issues),
                detail="Missing/duplicate constraint names",
            )
        )

    score = max(0, 100 - sum(d.points for d in deductions))
    if hard_error:
        for code, detail in (
            (lb_gt_ub, "Infeasible bounds (lb > ub)"),
            (constant_infeasible, "Trivially infeasible constraint"),
            (nonfinite_coef or nonfinite_bound, "Non-finite coefficient/bound"),
        ):
            if code:
                deductions.append(HealthDeduction(code="hard_error", points=0, detail=detail))
        score = min(score, 39)
    health = ModelHealth(
        score=score, band=_band(score), deductions=deductions, has_hard_error=hard_error
    )

    return ModelStats(
        var_total=var_total,
        var_continuous=var_continuous,
        var_integer=var_integer,
        var_binary=var_binary,
        constraint_total=constraint_total,
        constraints_by_operator=by_op,
        objective_sense=sense if isinstance(sense, str) else None,
        objective_terms=obj_terms,
        objective_quadratic=obj_quadratic,
        nonzeros=nonzeros,
        density=density,
        integrality_ratio=integrality_ratio,
        bound_profile=BoundProfile(
            free=free,
            boxed=boxed,
            one_sided=one_sided,
            binary=binary,
            integers_missing_bounds=integers_missing_bounds,
        ),
        conditioning=CoefConditioning(
            min_abs=min_abs, max_abs=max_abs, range_ratio=ratio, tier=tier
        ),
        problem_class=problem_class,
        warnings=warnings,
        health=health,
        content_hash=content_hash or "",
    )


def _incomplete_stats(content_hash: str) -> ModelStats:
    """Stats for a draft that does not yet validate as an OptimizationProblem."""
    return ModelStats(
        warnings=["Model is incomplete or not yet valid."],
        health=ModelHealth(score=50, band="D", deductions=[], has_hard_error=False),
        content_hash=content_hash,
    )


def compute_from_json(model_json: dict[str, Any] | None) -> ModelStats:
    """Compute stats from a raw ``model_json`` dict (a project draft / version snapshot).

    Never raises — an incomplete/invalid draft yields a flagged best-effort result.
    """
    chash = _content_hash(model_json)
    try:
        problem = OptimizationProblem.model_validate(model_json or {})
    except Exception:  # noqa: BLE001 — a half-built draft is expected, not exceptional
        return _incomplete_stats(chash)
    return compute(problem, content_hash=chash)


_redis_singleton: Any | None = None
_redis_initialized = False


def _redis_client() -> Any | None:
    """Best-effort Redis client, created once and reused (returns None when unavailable).

    The live-stats endpoint calls this on every debounced edit; a fresh
    ``Redis.from_url`` per call would spin up a new connection pool each time. The
    client is lazily built once and cached at module level (``redis.Redis`` is
    thread-safe and pools connections internally).
    """
    global _redis_singleton, _redis_initialized
    if _redis_initialized:
        return _redis_singleton
    _redis_initialized = True
    try:
        from app.config import settings  # noqa: PLC0415

        url = getattr(settings, "REDIS_URL", "") or ""
        if not url:
            return None
        import redis  # noqa: PLC0415

        _redis_singleton = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
    except Exception as exc:  # pragma: no cover - infra optional
        logger.debug("ModelStats cache unavailable: %s", exc)
        _redis_singleton = None
    return _redis_singleton


def compute_cached(model_json: dict[str, Any] | None) -> ModelStats:
    """Hash-keyed cached variant for the live-stats endpoint."""
    chash = _content_hash(model_json)
    client = _redis_client()
    key = f"modelstats:{chash}"
    if client is not None:
        try:
            cached = client.get(key)
            if cached:
                return ModelStats.model_validate_json(cached)
        except Exception as exc:  # pragma: no cover
            logger.debug("ModelStats cache read failed: %s", exc)
    stats = compute_from_json(model_json)
    if client is not None:
        try:
            client.set(key, stats.model_dump_json(), ex=_CACHE_TTL_SECONDS)
        except Exception as exc:  # pragma: no cover
            logger.debug("ModelStats cache write failed: %s", exc)
    return stats
