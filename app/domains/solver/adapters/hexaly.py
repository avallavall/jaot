"""HexalyAdapter — Phase 7.4 platform-license model.

Implements the SolverAdapter Protocol for the Hexaly Optimizer (commercial
metaheuristic). Key design points:

- **Lazy import**: the ``hexaly`` package is NEVER imported at module load
  time — only inside ``is_available()`` and ``solve()``. This keeps the base
  worker image free of the commercial SDK (the Hexaly-enabled image is a
  separate build target; see ``deploy/docker/Dockerfile.worker.hexaly``).

- **Platform license at construction** (D-01): ``__init__`` reads
  ``/etc/jaot/hexaly.lic`` (volume-mounted from the deploy host) and
  fail-fasts if the file is missing or already-expired. Only the
  ``celery_worker_hexaly`` container needs the file; other workers are
  unaffected. The plaintext lives on ``self._license_plaintext`` and is
  scoped into the process env per solve via ``hexaly_license_scope``.

- **License activation via ``HX_LICENSE_CONTENT`` env var**: plaintext is
  injected into the process environment inside a ``try/finally`` context
  manager so it is cleared even on exception. Pre-existing values are
  restored (defense-in-depth for nested calls / preset test environments).

- **``is_available()`` reports ONLY SDK-importable state.** License validity
  is enforced by ``__init__`` (fail-fast). Combined this gives the gate path
  the right granularity: SDK present + license loaded → solve; otherwise the
  container is unhealthy and the auto-router probes via the worker queue.

- **Quadratic expression translation**: ``_build_expression`` consumes a
  ``ParsedExpression`` from the shared ``ExpressionParser`` and emits native
  Hexaly expressions (``x * y`` for quadratic terms — no convexification
  pass, Hexaly handles non-convex natively).

- **Phase-based time limit**: ``optimizer.param.time_limit`` is set from
  ``OptimizationProblem.options.time_limit_seconds`` — Hexaly's metaheuristic
  requires an explicit stop criterion.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from app.domains.solver.adapters._license_utils import extract_expires_at, fingerprint
from app.domains.solver.adapters.base import SolverCapabilities, SolverError
from app.domains.solver.services.expression_parser import (
    ExpressionParser,
    ParsedExpression,
)
from app.schemas.optimization import (
    ObjectiveSense,
    OptimizationProblem,
    OptimizationResult,
    SolverStatus,
    VariableSolution,
    VariableType,
)
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)

_DEFAULT_TIME_LIMIT_SECONDS = 60

# Volume mount path per D-01 — root:root 0600 on the deploy host. Module-level
# constant so tests can monkeypatch it. Plan 06 (expiry sweep) imports the same
# constant from this module's scope (do not duplicate).
HEXALY_LIC_PATH: Path = Path("/etc/jaot/hexaly.lic")


def _resolve_time_limit(
    override: int | None,
    problem_limit: float | None,
) -> int:
    """Resolve the effective Hexaly time limit in seconds.

    Priority: explicit adapter override > problem.options.time_limit_seconds
    > module default. Kept as a separate helper so the precedence stays
    obvious at the call site instead of a nested ternary.
    """
    if override is not None:
        return int(override)
    if problem_limit is not None:
        return int(problem_limit)
    return _DEFAULT_TIME_LIMIT_SECONDS


@contextmanager
def hexaly_license_scope(plaintext: str) -> Iterator[None]:
    """Set ``HX_LICENSE_CONTENT`` for the duration of a with-block, then clear.

    Hexaly reads ``HX_LICENSE_CONTENT`` at ``HexalyOptimizer()`` construction
    time and it takes priority over file-based lookups. Restoring the previous
    value (instead of blindly deleting) is defense-in-depth for nested calls
    and test environments that preset the variable.

    Pitfall 2 guard: any exception inside the with-block MUST NOT leak the
    license to the next task running on the same Celery worker process.

    Raises:
        ValueError: if ``plaintext`` is empty (defense against silent
            misactivation).
    """
    if not plaintext:
        raise ValueError("license plaintext must not be empty")

    previous = os.environ.get("HX_LICENSE_CONTENT")
    os.environ["HX_LICENSE_CONTENT"] = plaintext
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("HX_LICENSE_CONTENT", None)
        else:
            os.environ["HX_LICENSE_CONTENT"] = previous


class HexalyAdapter:
    """Hexaly Optimizer adapter (commercial; platform-license model).

    Implements the SolverAdapter Protocol structurally. The ``solve()`` method
    accepts additional keyword-only parameters (``license_plaintext``,
    ``time_limit_seconds``) beyond the Protocol's minimal signature — Python
    Protocols are structural, so adding optional kwargs does not violate the
    contract (callers that only pass ``warm_start`` still type-check).
    """

    capabilities: SolverCapabilities = SolverCapabilities(
        name="hexaly",
        supports_continuous=True,
        supports_integer=True,
        supports_binary=True,
        supports_quadratic=True,
        supports_sensitivity=False,
        supports_warm_start=True,
        supports_multi_objective=False,
        # Phase 7.4 / D-10: requires_license removed — license loaded in __init__ (Plan 02).
    )

    def __init__(self) -> None:
        """Load the platform Hexaly license at construction time.

        Phase 7.4 / D-01 / D-11 / HEX-08:
        - Reads ``/etc/jaot/hexaly.lic`` (volume-mounted from the deploy host).
        - Parses fingerprint (sha256 prefix) and expires_at (regex scan).
        - Fails fast (RuntimeError) when the file is missing OR parses as
          already-expired — the celery_worker_hexaly container crashes and the
          Docker healthcheck marks it unhealthy. Other workers (default/scip/
          highs) are unaffected.

        NOTE: ``HX_LICENSE_CONTENT`` env var is NOT set here. License activation
        stays scoped to each ``solve()`` call via ``hexaly_license_scope`` —
        defense-in-depth keeps a leaked exception from leaving the env var set
        for the next task on the same worker process.
        """
        self._parser = ExpressionParser()

        if not HEXALY_LIC_PATH.exists():
            raise RuntimeError(
                f"Platform Hexaly license not found at {HEXALY_LIC_PATH}. "
                "Mount the .lic file via docker-compose volume (see D-01)."
            )

        self._license_plaintext: str = HEXALY_LIC_PATH.read_text(encoding="utf-8")
        plaintext_bytes = HEXALY_LIC_PATH.read_bytes()
        self._license_fingerprint: str = fingerprint(plaintext_bytes)
        self._license_expires_at: datetime | None = extract_expires_at(plaintext_bytes)

        if self._license_expires_at is not None and self._license_expires_at <= utcnow():
            raise RuntimeError(
                f"Platform Hexaly license expired at {self._license_expires_at.isoformat()}. "
                f"Replace {HEXALY_LIC_PATH} with a renewed .lic and restart the worker."
            )

        logger.info(
            "Platform Hexaly license loaded: fingerprint=%s expires_at=%s",
            self._license_fingerprint,
            self._license_expires_at.isoformat() if self._license_expires_at else "unknown",
        )

    def is_available(self) -> bool:
        """Return True when ``hexaly.optimizer`` is importable.

        Delegates to ``hexaly_availability.hexaly_available()`` — the module
        cache is the single source of truth. Previously the adapter held its
        own ``_available`` cache that could drift from the module cache when
        tests cleared one but not the other. Tests now only call
        :func:`hexaly_availability._reset_cache_for_tests`.
        """
        from app.domains.solver.adapters.hexaly_availability import (  # noqa: PLC0415
            hexaly_available,
        )

        return hexaly_available()

    # Phase 7.4 / D-10: validate_license removed — license loaded in __init__ (Plan 02).

    def solve(
        self,
        problem: OptimizationProblem,
        *,
        warm_start: dict[str, float] | None = None,
        license_plaintext: str | None = None,
        time_limit_seconds: int | None = None,
    ) -> OptimizationResult:
        """Solve ``problem`` on the Hexaly optimizer.

        Args:
            problem: Solver-agnostic ``OptimizationProblem``. Variables with
                ``CONTINUOUS`` / ``INTEGER`` / ``BINARY`` types are mapped to
                ``model.float`` / ``model.int`` / ``model.bool``.
            warm_start: Optional initial solution (mapping var-name → value).
                Accepted for Protocol compatibility; Hexaly warm-start hook is
                wired in a later phase (D-11 flags supports_warm_start=True
                but expression walker is the Phase 7 scope).
            license_plaintext: Backwards-compat kwarg from the BYOL era.
                Phase 7.4 / D-01 loads the platform license at ``__init__``
                so this argument is ignored when ``self._license_plaintext``
                is set. Kept on the signature so older callers do not break;
                slated for removal in a follow-up phase.
            time_limit_seconds: Override for ``optimizer.param.time_limit``.
                Defaults to ``OptimizationProblem.options.time_limit_seconds``
                when omitted; ultimate fallback is 60s (D-12 explicit-stop).

        Returns:
            An ``OptimizationResult``. Status is mapped from
            ``HxSolutionStatus`` (see ``_map_hexaly_status``). Solution values
            are read directly from the Hexaly variables post-solve.

        Raises:
            SolverError: if the Hexaly SDK is not installed on this worker.
            ValueError: if ``license_plaintext`` is empty or ``None``.
        """
        if not self.is_available():
            raise SolverError("Hexaly SDK is not installed on this worker")

        # Phase 7.4 / D-01: prefer the platform license loaded at __init__.
        # The license_plaintext kwarg is kept for backwards-compat but ignored when
        # the platform license is loaded — single source of truth is self._license_plaintext.
        effective_plaintext = self._license_plaintext or license_plaintext
        if not effective_plaintext:
            raise ValueError("hexaly_platform_license_not_loaded")

        if warm_start is not None:
            logger.debug(
                "HexalyAdapter received warm_start (size=%d); wiring deferred "
                "to a follow-up plan — ignoring for now.",
                len(warm_start),
            )

        effective_time_limit = _resolve_time_limit(
            time_limit_seconds, problem.options.time_limit_seconds
        )

        # Lazy imports — NEVER at module top level.
        import hexaly.optimizer as hxopt  # noqa: PLC0415

        start_time = time.time()

        known_variables = [v.name for v in problem.variables]

        try:
            with hexaly_license_scope(effective_plaintext):
                with hxopt.HexalyOptimizer() as optimizer:
                    model = optimizer.model
                    hex_vars = self._declare_variables(model, problem)

                    parsed_objective = self._parser.parse_expression(
                        problem.objective.expression,
                        known_variables=known_variables,
                    )
                    objective_expr = self._build_expression(model, parsed_objective, hex_vars)
                    if problem.objective.sense == ObjectiveSense.MAXIMIZE:
                        model.maximize(objective_expr)
                    else:
                        model.minimize(objective_expr)

                    for i, constraint in enumerate(problem.constraints):
                        self._add_constraint(
                            model,
                            hex_vars,
                            constraint,
                            known_variables,
                            default_name=f"c{i}",
                        )

                    model.close()
                    optimizer.param.time_limit = int(effective_time_limit)
                    optimizer.solve()

                    return self._extract_result(
                        optimizer, hex_vars, problem, objective_expr, start_time
                    )
        except SolverError:
            raise
        except ValueError:
            raise
        except Exception as exc:
            # Hexaly SDK exception strings can carry internal paths /
            # license-state hints. Never echo into the response (WR-03);
            # log server-side, return a bounded error code.
            logger.error("Hexaly solver error: %s", exc, exc_info=True)
            return OptimizationResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=time.time() - start_time,
                error_message="hexaly_internal_error",
            )

    def _declare_variables(self, model: Any, problem: OptimizationProblem) -> dict[str, Any]:
        """Translate ``problem.variables`` into Hexaly variable handles.

        - CONTINUOUS → ``model.float(lb, ub)``
        - INTEGER    → ``model.int(lb, ub)``
        - BINARY     → ``model.bool()``
        """
        hex_vars: dict[str, Any] = {}
        for var in problem.variables:
            if var.type == VariableType.CONTINUOUS:
                lb = var.lower_bound if var.lower_bound is not None else -1e30
                ub = var.upper_bound if var.upper_bound is not None else 1e30
                hex_vars[var.name] = model.float(float(lb), float(ub))
            elif var.type == VariableType.INTEGER:
                lb = int(var.lower_bound) if var.lower_bound is not None else -(10**9)
                ub = int(var.upper_bound) if var.upper_bound is not None else 10**9
                hex_vars[var.name] = model.int(lb, ub)
            elif var.type == VariableType.BINARY:
                hex_vars[var.name] = model.bool()
            else:
                raise SolverError(f"Unsupported variable type for Hexaly: {var.type}")
        return hex_vars

    def _build_expression(
        self,
        model: Any,
        parsed: ParsedExpression,
        hex_vars: dict[str, Any],
    ) -> Any:
        """Translate a ``ParsedExpression`` into a native Hexaly expression.

        D-10 / D-13: supports constants, linear (``coef * x``), and quadratic
        (``coef * x * y``, including ``x * x``) terms. No convexification —
        Hexaly handles non-convex problems natively. Higher-degree terms
        (> 2 variables) are rejected explicitly.
        """
        terms: list[Any] = []
        if parsed.constant:
            terms.append(parsed.constant)

        for term in parsed.terms:
            if not term.variables:
                # Pure constant term (rare after consolidation — constants fold into .constant).
                terms.append(term.coefficient)
            elif len(term.variables) == 1:
                terms.append(term.coefficient * hex_vars[term.variables[0]])
            elif len(term.variables) == 2:
                v1, v2 = term.variables
                terms.append(term.coefficient * (hex_vars[v1] * hex_vars[v2]))
            else:
                raise SolverError(
                    f"Hexaly adapter does not support terms with >2 variables: {term.variables}"
                )

        if not terms:
            return 0
        if len(terms) == 1:
            return terms[0]
        return model.sum(terms)

    def _add_constraint(
        self,
        model: Any,
        hex_vars: dict[str, Any],
        constraint: Any,
        known_variables: list[str],
        default_name: str,
    ) -> None:
        """Parse a constraint string and attach it to the Hexaly model.

        Constraint expressions are in the form ``<lhs> <op> <rhs>`` (e.g.
        ``"x + 2*y <= 10"``). After the shared parser moves all variable
        terms to LHS and constants to RHS, we emit ``model.constraint(lhs op rhs)``
        using the operator directly — Hexaly's Python API supports ``<=``,
        ``>=``, and ``==`` via Python operator overloading on expressions.
        """
        parsed = self._parser.parse_constraint(
            constraint.expression, known_variables=known_variables
        )
        lhs_expr = self._build_expression(model, parsed.lhs, hex_vars)
        op = parsed.operator
        rhs = float(parsed.rhs)

        if op in ("<=", "<"):
            model.constraint(lhs_expr <= rhs)
        elif op in (">=", ">"):
            model.constraint(lhs_expr >= rhs)
        elif op in ("==", "="):
            model.constraint(lhs_expr == rhs)
        else:
            logger.warning(
                "Unknown constraint operator %r for constraint %r — skipping.",
                op,
                constraint.name or default_name,
            )

    def _extract_result(
        self,
        optimizer: Any,
        hex_vars: dict[str, Any],
        problem: OptimizationProblem,
        objective_expr: Any,
        start_time: float,
    ) -> OptimizationResult:
        """Build an ``OptimizationResult`` from the solved Hexaly model."""
        status = self._map_hexaly_status(optimizer.solution.status)
        solve_time = time.time() - start_time

        if status not in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
            return OptimizationResult(
                status=status,
                solve_time_seconds=solve_time,
            )

        variable_solutions: list[VariableSolution] = []
        solution: dict[str, float] = {}
        for var_def in problem.variables:
            handle = hex_vars[var_def.name]
            raw_value = handle.value
            if var_def.type in (VariableType.INTEGER, VariableType.BINARY):
                raw_value = round(float(raw_value))
            float_value = float(raw_value)
            variable_solutions.append(
                VariableSolution(name=var_def.name, value=float_value, type=var_def.type)
            )
            solution[var_def.name] = float_value

        # Objective value is read from the objective HxExpression's `.value`
        # attribute. The Hexaly Python API's HxSolution has no get_objective();
        # objectives and variables are both HxExpression and expose `.value`
        # after solve (HxSolution.get_value(expr) is the equivalent). A purely
        # constant objective is a raw Python number, so fall back to it directly.
        try:
            objective_value: float | None = float(
                objective_expr.value if hasattr(objective_expr, "value") else objective_expr
            )
        except Exception:
            logger.debug(
                "Could not extract Hexaly objective value; leaving as None.",
                exc_info=True,
            )
            objective_value = None

        return OptimizationResult(
            status=status,
            objective_value=objective_value,
            variables=variable_solutions,
            solution=solution,
            solve_time_seconds=solve_time,
        )

    # Status mapping — lazy to avoid module-load SDK import

    def _map_hexaly_status(self, hexaly_status: Any) -> SolverStatus:
        """Map a ``HxSolutionStatus`` enum value to our ``SolverStatus``.

        Imports the Hexaly enum lazily — we're already inside ``solve()`` at
        this point, so the SDK is guaranteed to be importable. Matching by
        ``name`` (string) keeps us independent of SDK version pin drift on
        enum value ordinals.
        """
        try:
            from hexaly.optimizer import HxSolutionStatus  # noqa: PLC0415

            mapping = {
                HxSolutionStatus.OPTIMAL: SolverStatus.OPTIMAL,
                HxSolutionStatus.FEASIBLE: SolverStatus.FEASIBLE,
                HxSolutionStatus.INFEASIBLE: SolverStatus.INFEASIBLE,
                HxSolutionStatus.INCONSISTENT: SolverStatus.INFEASIBLE,
            }
            mapped = mapping.get(hexaly_status)
            if mapped is not None:
                return mapped
        except Exception:
            logger.debug(
                "Hexaly status mapping fell through to name-based match",
                exc_info=True,
            )

        # Fallback: match by the string name of the enum member — resilient to
        # SDK minor-version enum additions.
        name = getattr(hexaly_status, "name", "") or str(hexaly_status)
        name = name.upper()
        if "OPTIMAL" in name:
            return SolverStatus.OPTIMAL
        if "INFEASIBLE" in name or "INCONSISTENT" in name:
            return SolverStatus.INFEASIBLE
        if "FEASIBLE" in name:
            return SolverStatus.FEASIBLE
        return SolverStatus.ERROR
