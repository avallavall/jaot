"""An imported file must be the model the file describes, or be refused.

# CONTRACT-TEST: an imported model solves to the same optimum as its file.

Each case was a file that imported "successfully" as a different model
(2026-09-24):

- ``x.1`` and ``x_1`` both sanitize to ``x_1``. The variable list kept them
  apart, but the objective and every row used ``x_1`` for both, so the second
  variable sat in no row and the model turned infeasible.
- The objective constant of an LP or MPS file was dropped.
- One quadratic row sent the whole model through the CIP fallback, which read
  ``+1e-05<x>`` as ``-5*x``, dropped the quadratic row, dropped the lower side of
  every ranged row, and named rows ``_c1_``.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from pyscipopt import Model

from app.domains.solver.adapters._scip_import import FileImportError, FileImportService
from app.domains.solver.adapters.scip import SCIPAdapter
from app.domains.solver.services.cip_parser import UnreadCipRowsError, parse_cip_constraints
from app.schemas.optimization import SolverStatus

pytestmark = pytest.mark.unit


def _lp_bytes(build) -> bytes:
    model = Model()
    model.hideOutput()
    build(model)
    fd, path = tempfile.mkstemp(suffix=".lp")
    os.close(fd)
    try:
        model.writeProblem(path, verbose=False)
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        os.unlink(path)


def _import(build):
    return FileImportService().import_from_file(_lp_bytes(build), "model.lp")


def test_two_names_that_sanitize_alike_stay_two_variables() -> None:
    def build(m: Model) -> None:
        a = m.addVar("x.1", lb=0)
        b = m.addVar("x_1", lb=0)
        m.addCons(a + b >= 3, name="c1")
        m.addCons(a <= 1, name="c2")
        m.setObjective(a + 2 * b, "minimize")

    problem = _import(build)
    names = sorted(v.name for v in problem.variables)
    assert len(set(names)) == 2
    result = SCIPAdapter().solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(5.0)  # x.1 = 1, x_1 = 2


def test_the_objective_constant_survives_the_import() -> None:
    def build(m: Model) -> None:
        x = m.addVar("x", lb=0, ub=10)
        m.addCons(x >= 2, name="floor")
        m.setObjective(3 * x + 100, "minimize")

    problem = _import(build)
    result = SCIPAdapter().solve(problem)
    assert result.objective_value == pytest.approx(106.0)


def test_a_file_with_a_quadratic_row_is_refused_not_trimmed() -> None:
    def build(m: Model) -> None:
        x = m.addVar("x", lb=0, ub=10)
        y = m.addVar("y", lb=0, ub=10)
        m.addCons(0.00001 * x + y <= 4, name="c1")
        m.addCons(x * x + y * y <= 8, name="q1")
        m.setObjective(3 * x + 2 * y, "maximize")

    with pytest.raises(FileImportError) as caught:
        _import(build)
    assert caught.value.code == "import.unsupported_constraints"
    assert caught.value.params == {"kinds": {"nonlinear": 1}}


def _cip_rows(text: str, **kwargs):
    fd, path = tempfile.mkstemp(suffix=".cip")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return parse_cip_constraints(path, **kwargs)
    finally:
        os.unlink(path)


_CIP = """STATISTICS
  Problem name     : model
VARIABLES
  [continuous] <x_1>: obj=2, original bounds=[0,10]
  [continuous] <x.1>: obj=3, original bounds=[0,10]
CONSTRAINTS
  [linear] <c1>:  +1e-05<x.1>[C] +<x_1>[C] <= 4;
  [linear] <rng>: -5 <= <x.1>[C] -<x_1>[C] <= 10;
  [linear] <big>:  +2.5<x.1>[C] [free];
  [nonlinear] <q1>: <x.1>*<x.1>+<x_1>*<x_1> <= 8;
END
"""


def test_the_cip_fallback_reads_what_scip_writes() -> None:
    rows = _cip_rows(_CIP, var_names={"x.1": "x_1", "x_1": "x_1_1"})
    by_name = {row.name: row.expression for row in rows}
    # Angle brackets are SCIP's quoting, not part of the name.
    assert set(by_name) == {"c1", "rng", "rng_lb"}
    # The exponent belongs to the coefficient: this used to read -5*x_1.
    assert by_name["c1"] == "1e-05*x_1 +x_1_1 <= 4"
    # Both sides of a ranged row.
    assert by_name["rng"] == "x_1 -x_1_1 <= 10"
    assert by_name["rng_lb"] == "x_1 -x_1_1 >= -5"


def test_the_cip_fallback_names_the_rows_it_cannot_read() -> None:
    with pytest.raises(UnreadCipRowsError) as caught:
        _cip_rows(_CIP, strict=True)
    assert dict(caught.value.kinds) == {"nonlinear": 1}
