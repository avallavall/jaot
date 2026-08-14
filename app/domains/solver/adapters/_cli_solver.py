"""Shared plumbing for solvers JAOT drives as a separate process.

GLPK is GPLv3 and JAOT is Apache-2.0. Linking GLPK's library into this process
would put JAOT's own code under the GPL, so ``glpsol`` runs as its own process
and JAOT only writes its input and reads its output. CBC is EPL-2.0 and carries
no such condition, but it takes the same path so there is one way of driving a
command-line solver here and not two.

The exchange format is CPLEX LP, written by SCIP. MPS was tried first and
dropped: SCIP writes the objective sense in an ``OBJSENSE`` section, CBC prints
"MAX found after OBJSENSE - Coin ignores" and then minimizes, and GLPK refuses
the file with "invalid indicator record". A maximization solved as a
minimization is a wrong answer with no error attached, which is the one failure
this module must never produce.
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess  # noqa: S404 — the whole point of this module is running a binary
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.domains.solver.adapters._scip_model_builder import build_scip_model
from app.domains.solver.adapters.base import SolverError
from app.schemas.optimization import OptimizationProblem

logger = logging.getLogger(__name__)

#: SCIP's name for a constraint it can express as a plain linear row. Anything
#: else means the LP file will carry a section a command-line MILP solver
#: cannot read — see :func:`write_problem_lp`.
_LINEAR_CONSHDLR = "linear"


def find_binary(name: str) -> str | None:
    """Absolute path of ``name`` on PATH, or None when it is not installed."""
    return shutil.which(name)


def hard_timeout_seconds(time_limit_seconds: float) -> float:
    """How long to wait before killing the child outright.

    The solver's own limit is a request, not a guarantee. CBC counts CPU
    seconds and checks the clock only between nodes: asked for 5 it came back
    after 6.6 seconds of wall time. The comparison worker runs at concurrency 1,
    so a child that keeps going holds up every comparison behind it.

    Half again plus ten seconds covers the overshoot measured on both solvers
    and still bounds the wait on a long limit.
    """
    return time_limit_seconds * 1.5 + 10.0


@dataclass(frozen=True)
class CliRun:
    """What came back from one run of a solver binary."""

    stdout: str
    returncode: int | None
    #: True when the hard timeout expired and the child was killed. The solver
    #: never got to write its answer, so nothing it left behind can be trusted.
    killed: bool


def run_binary(argv: list[str], *, timeout: float) -> CliRun:
    """Run ``argv`` and capture its output, killing it if it overruns.

    stderr is folded into stdout: both solvers write their progress and their
    verdict to stdout, and the few lines they send to stderr belong in the same
    log when a run has to be explained.
    """
    logger.debug("Running solver binary: %s", " ".join(argv))
    try:
        completed = subprocess.run(  # noqa: S603 — argv list, never a shell string
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("Killed %s after %.1fs (hard timeout)", argv[0], timeout)
        return CliRun(
            stdout=_as_text(exc.stdout) + _as_text(exc.stderr), returncode=None, killed=True
        )
    return CliRun(
        stdout=completed.stdout + completed.stderr,
        returncode=completed.returncode,
        killed=False,
    )


def _as_text(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


@contextmanager
def workspace(prefix: str) -> Iterator[Path]:
    """A temporary directory for one solve, removed whatever happens.

    The containers run with a read-only root filesystem and a tmpfs on ``/tmp``,
    which is where ``mkdtemp`` lands. Nothing here may be written next to the
    application code.
    """
    path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def write_problem_lp(problem: OptimizationProblem, path: Path, *, solver_label: str) -> None:
    """Write ``problem`` to ``path`` as a CPLEX LP file.

    Raises ``SolverError`` when the model is not linear. That check is not
    politeness: CBC reads an LP file whose only constraint is quadratic, drops
    what it does not understand and reports "Optimal" on the remains. It is the
    one input this module refuses rather than passes on.

    The check costs nothing extra. ``build_scip_model`` has to run anyway to
    write the file, and SCIP files a quadratic row under its ``nonlinear``
    constraint handler while every linear row lands under ``linear`` — so the
    model already knows the answer and nothing has to be parsed a second time.
    """
    model, _, _ = build_scip_model(problem)
    handlers = {cons.getConshdlrName() for cons in model.getConss()}
    nonlinear = handlers - {_LINEAR_CONSHDLR}
    if nonlinear:
        raise SolverError(
            f"{solver_label} solves linear problems only — this model carries "
            "quadratic terms. Use SCIP (or automatic selection) for quadratic models."
        )
    model.writeProblem(str(path), verbose=False)


def relative_gap(objective_value: float | None, dual_bound: float | None) -> float | None:
    """Distance left between the answer and the best bound, as a fraction.

    Computed here rather than read from the solver. CBC prints its gap rounded
    to two decimals, which turns a real 0.004 into "0.00" and a closed search
    into "-0.00"; GLPK prints "< 0.1%" once the gap is small. Both solvers do
    report the two numbers the gap is made of, so JAOT divides them itself and
    every solver's gap column then means the same thing.
    """
    if objective_value is None or dual_bound is None:
        return None
    if not math.isfinite(objective_value) or not math.isfinite(dual_bound):
        return None
    denominator = max(abs(objective_value), 1e-10)
    return abs(objective_value - dual_bound) / denominator


def parse_float(token: str) -> float | None:
    """Float from one output token, or None when it is not a number.

    Solver logs put words where numbers go — "not found yet", "tree is empty",
    "+inf". They mean the solver has nothing to report, which is not the same as
    a very large number, so they come back as None.
    """
    try:
        value = float(token)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def tail(text: str, *, lines: int = 12, max_chars: int = 1200) -> str:
    """The last few lines of solver output, for an error message.

    A failing solver can print hundreds of lines. The reason is always at the
    end, and the whole log on a user's screen is what the comparison page
    already had to be fixed for once.
    """
    trimmed = "\n".join(text.strip().splitlines()[-lines:])
    if len(trimmed) > max_chars:
        trimmed = trimmed[-max_chars:]
    return trimmed
