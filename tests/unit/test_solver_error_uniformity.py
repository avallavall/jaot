"""D-05 / WR-03 — an unusable solver refuses the same way whatever the reason.

``GET /solvers/available`` lists only adapters whose ``is_available()`` is true, so
a commercial solver that is installed but unlicensed is deliberately absent from it.
The refusal messages used to give that back: one said a name was *not registered*,
the other that it *was registered but unavailable*. Probing names therefore
enumerated which commercial solvers the deployment carries — information about the
operator's licences, not about the caller's request.
"""

from app.api.v2.solver_errors import solver_unavailable
from app.domains.solver.adapters.base import SolverNotFoundError, SolverUnavailableError


def _detail(exc_type: type[Exception], message: str, name: str) -> str:
    http_exc = solver_unavailable(exc_type(message), name)  # type: ignore[arg-type]
    return str(http_exc.detail)


class TestSolverRefusalIsUniform:
    # CONTRACT-TEST: the two failure modes must be indistinguishable to a client.
    def test_missing_and_unlicensed_produce_the_same_body(self):
        missing = _detail(SolverNotFoundError, "Solver 'gurobi' is not registered.", "gurobi")
        unlicensed = _detail(
            SolverUnavailableError,
            "Solver 'gurobi' is registered but not available at runtime.",
            "gurobi",
        )

        assert missing == unlicensed

    def test_the_body_never_says_whether_the_solver_is_registered(self):
        for exc_type, message in (
            (SolverNotFoundError, "Solver 'cplex' is not registered."),
            (SolverUnavailableError, "Solver 'cplex' is registered but not available at runtime."),
        ):
            detail = _detail(exc_type, message, "cplex").lower()
            assert "registered" not in detail
            assert "runtime" not in detail
            assert "licen" not in detail

    def test_the_body_never_enumerates_other_solvers(self):
        detail = _detail(
            SolverNotFoundError,
            "Solver 'gurobi' is not registered. Registered: ['scip', 'highs', 'hexaly']",
            "gurobi",
        ).lower()

        for installed in ("scip", "highs", "hexaly", "registered:"):
            assert installed not in detail

    def test_the_requested_name_is_echoed_back(self):
        """The caller already knows what they asked for — echoing it aids debugging."""
        assert "gurobi" in _detail(SolverNotFoundError, "whatever", "gurobi")

    def test_a_missing_name_does_not_crash_the_refusal(self):
        detail = _detail(SolverNotFoundError, "no name given", None)  # type: ignore[arg-type]
        assert detail

    def test_it_is_a_422(self):
        assert solver_unavailable(SolverNotFoundError("x"), "gurobi").status_code == 422
