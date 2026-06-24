"""Cross-solver consistency tests — Phase 5 / HIGH-03.

Verifies SCIP and HiGHS produce the same results within 1e-6 relative
tolerance for LP, MIP, infeasible/unbounded, and file-import problems.

All tests are RED until Plan 02 (HiGHSAdapter) completes.
"""

from app.schemas.optimization import (
    Constraint,
    Objective,
    OptimizationProblem,
    SolverOptions,
    SolverStatus,
    Variable,
    VariableType,
)

_TOLERANCE = 1e-6


def _relative_diff(a: float, b: float) -> float:
    return abs(a - b) / max(1.0, abs(a))


def _lp_problem() -> OptimizationProblem:
    """LP: minimize 2x + 3y s.t. x+y>=4, x>=0, y>=0."""
    return OptimizationProblem(
        name="crosscheck_lp",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0.0),
        ],
        constraints=[
            Constraint(expression="x + y >= 4"),
        ],
        objective=Objective(expression="2*x + 3*y", sense="minimize"),
        options=SolverOptions(time_limit_seconds=30.0, verbose=False),
    )


def _mip_problem() -> OptimizationProblem:
    """MIP: maximize 3x + 5y s.t. x+y<=4, x integer, y binary."""
    return OptimizationProblem(
        name="crosscheck_mip",
        variables=[
            Variable(name="x", type=VariableType.INTEGER, lower_bound=0.0, upper_bound=4.0),
            Variable(name="y", type=VariableType.BINARY),
        ],
        constraints=[
            Constraint(expression="x + y <= 4"),
        ],
        objective=Objective(expression="3*x + 5*y", sense="maximize"),
        options=SolverOptions(time_limit_seconds=30.0, verbose=False),
    )


def _infeasible_problem() -> OptimizationProblem:
    return OptimizationProblem(
        name="crosscheck_infeasible",
        variables=[Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0)],
        constraints=[
            Constraint(expression="x >= 10"),
            Constraint(expression="x <= 5"),
        ],
        objective=Objective(expression="x", sense="minimize"),
        options=SolverOptions(time_limit_seconds=30.0, verbose=False),
    )


class TestCrossSolverConsistency:
    """SCIP and HiGHS must agree within 1e-6 relative tolerance."""

    def test_lp_crosscheck(self) -> None:
        """LP objective values match within 1e-6 relative tolerance."""
        from app.domains.solver.adapters.highs import HiGHSAdapter  # noqa: PLC0415
        from app.domains.solver.adapters.scip import SCIPAdapter  # noqa: PLC0415

        problem = _lp_problem()
        scip_result = SCIPAdapter().solve(problem)
        highs_result = HiGHSAdapter().solve(problem)

        assert scip_result.status == SolverStatus.OPTIMAL
        assert highs_result.status == SolverStatus.OPTIMAL
        assert scip_result.objective_value is not None
        assert highs_result.objective_value is not None
        assert (
            _relative_diff(scip_result.objective_value, highs_result.objective_value) < _TOLERANCE
        )

    def test_mip_crosscheck(self) -> None:
        """MIP objective values match within 1e-6 relative tolerance."""
        from app.domains.solver.adapters.highs import HiGHSAdapter  # noqa: PLC0415
        from app.domains.solver.adapters.scip import SCIPAdapter  # noqa: PLC0415

        problem = _mip_problem()
        scip_result = SCIPAdapter().solve(problem)
        highs_result = HiGHSAdapter().solve(problem)

        assert scip_result.status == SolverStatus.OPTIMAL
        assert highs_result.status == SolverStatus.OPTIMAL
        assert scip_result.objective_value is not None
        assert highs_result.objective_value is not None
        assert (
            _relative_diff(scip_result.objective_value, highs_result.objective_value) < _TOLERANCE
        )

    def test_status_crosscheck(self) -> None:
        """Infeasible problems return INFEASIBLE status from both solvers."""
        from app.domains.solver.adapters.highs import HiGHSAdapter  # noqa: PLC0415
        from app.domains.solver.adapters.scip import SCIPAdapter  # noqa: PLC0415

        problem = _infeasible_problem()
        assert SCIPAdapter().solve(problem).status == SolverStatus.INFEASIBLE
        assert HiGHSAdapter().solve(problem).status == SolverStatus.INFEASIBLE

    def test_file_import_crosscheck(self) -> None:
        """Same .lp file parsed and solved by both solvers gives matching objective."""
        from app.domains.solver.adapters.highs import HiGHSAdapter  # noqa: PLC0415
        from app.domains.solver.adapters.scip import SCIPAdapter  # noqa: PLC0415
        from app.domains.solver.services.file_import import get_file_import_service  # noqa: PLC0415

        # Minimal .lp file: minimize x + y s.t. x + y >= 6, x >= 0, y >= 0
        lp_content = (
            b"\\Problem name: crosscheck\n"
            b"Minimize\n"
            b" obj: x + y\n"
            b"Subject To\n"
            b" c1: x + y >= 6\n"
            b"Bounds\n"
            b" 0 <= x\n"
            b" 0 <= y\n"
            b"End\n"
        )
        importer = get_file_import_service()
        problem = importer.import_from_file(lp_content, "crosscheck.lp", None)

        scip_result = SCIPAdapter().solve(problem)
        highs_result = HiGHSAdapter().solve(problem)

        assert scip_result.status == SolverStatus.OPTIMAL
        assert highs_result.status == SolverStatus.OPTIMAL
        assert scip_result.objective_value is not None
        assert highs_result.objective_value is not None
        assert (
            _relative_diff(scip_result.objective_value, highs_result.objective_value) < _TOLERANCE
        )
