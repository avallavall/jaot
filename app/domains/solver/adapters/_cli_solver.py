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
import re
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

#: The two words SCIP writes above the objective row of an LP file.
_OBJECTIVE_SENSE_LINES = frozenset({"Minimize", "Maximize"})

#: A name in an LP file: a letter or underscore, then letters, digits or underscores.
_LP_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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


#: How long to wait for a binary asked only to print its version. Generous
#: enough for a cold start on a loaded machine, short enough that a hung binary
#: cannot hold up whatever asked.
_VERSION_TIMEOUT_SECONDS = 10.0


def read_version(argv: list[str], pattern: re.Pattern[str]) -> str | None:
    """Run ``argv`` and pull the version out of what it prints.

    Returns None whenever anything at all goes wrong: the binary is missing, it
    times out, or it prints something this pattern does not recognise. A version
    is a label on a stored table, so failing to read one must never stop a solve
    or fail a request.

    ``pattern`` must carry a group named ``version``.
    """
    try:
        run = run_binary(argv, timeout=_VERSION_TIMEOUT_SECONDS)
    except Exception as exc:  # pragma: no cover - run_binary already swallows its own
        logger.debug("Could not run %s to read its version: %s", argv[0], exc)
        return None
    if run.killed:
        logger.debug("%s did not answer within the version timeout", argv[0])
        return None
    match = pattern.search(run.stdout)
    if match is None:
        logger.debug("Could not find a version in what %s printed", argv[0])
        return None
    return match.group("version").strip()


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


def write_problem_lp(problem: OptimizationProblem, path: Path, *, solver_label: str) -> float:
    """Write ``problem`` to ``path`` as a CPLEX LP file; return the objective constant.

    Raises ``SolverError`` when the model is not linear. That check is not
    politeness: CBC reads an LP file whose only constraint is quadratic, drops
    what it does not understand and reports "Optimal" on the remains. It is the
    one input this module refuses rather than passes on.

    The check costs nothing extra. ``build_scip_model`` has to run anyway to
    write the file, and SCIP files a quadratic row under its ``nonlinear``
    constraint handler while every linear row lands under ``linear`` — so the
    model already knows the answer and nothing has to be parsed a second time.

    The returned number is the constant term taken out of the objective row.
    **The caller must add it back to every objective value it reports**, because
    the file no longer carries it — see :func:`_lift_constant_out_of_objective`.
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
    first_variable = model.getVars()[0].name if model.getVars() else None
    return _lift_constant_out_of_objective(path, first_variable)


def _lp_number(token: str) -> float | None:
    """The number a bare LP token holds, or None when the token is not one."""
    try:
        return float(token)
    except ValueError:
        return None


def _rewrite_objective_terms(terms: str) -> tuple[str, float, bool]:
    """Split one objective line into (terms without constants, constant, has a variable).

    An LP objective is a run of ``<coefficient> <name>`` pairs with, sometimes,
    a bare number among them. SCIP writes the objective offset as exactly such a
    bare number.
    """
    tokens = terms.split()
    kept: list[str] = []
    constant = 0.0
    has_variable = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if following is not None and _LP_NAME.fullmatch(following):
            kept.extend((token, following))
            has_variable = True
            index += 2
            continue
        if _LP_NAME.fullmatch(token):
            kept.append(token)
            has_variable = True
            index += 1
            continue
        value = _lp_number(token)
        if value is None:
            # Not a number and not a name: leave it exactly where it was rather
            # than guess. The file stays valid and the offset stays truthful.
            kept.append(token)
            index += 1
            continue
        constant += value
        index += 1
    return " ".join(kept), constant, has_variable


def _lift_constant_out_of_objective(path: Path, first_variable: str | None) -> float:
    """Take the constant out of the objective row, and return it.

    Neither command-line solver reads an LP objective that carries a bare
    number, and they disagree about how to fail:

    * glpsol refuses the whole file — "missing variable name", "CPLEX LP file
      processing error". A feasibility model (objective ``0``) is a normal
      thing to ask, and every one of them failed in 7 ms while the other
      solvers ran it, so a comparison lost a column to this writer rather than
      to anything about the model.
    * CBC reads the file, drops the constant without a word, and reports an
      objective short by exactly that amount. A wrong number with no error is
      the one failure this module exists to prevent.

    So the constant leaves the file and comes back in the caller's answer. An
    objective left with no variable at all gets ``+0 <name>``, which is the same
    objective and which both readers accept.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip() in _OBJECTIVE_SENSE_LINES),
        None,
    )
    if start is None or start + 1 >= len(lines):
        return 0.0

    constant = 0.0
    has_variable = False
    changed = False
    index = start + 1
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or _is_section_line(stripped):
            break
        head, separator, tail_terms = line.partition(":")
        # Only the first line of the objective carries the "Obj:" label; the
        # continuations SCIP wraps onto later lines are terms all the way.
        terms = tail_terms if separator and index == start + 1 else line
        prefix = f"{head}{separator}" if separator and index == start + 1 else ""
        rewritten, line_constant, line_has_variable = _rewrite_objective_terms(terms)
        constant += line_constant
        has_variable = has_variable or line_has_variable
        if rewritten != terms.strip():
            indent = line[: len(line) - len(line.lstrip())]
            lines[index] = f"{prefix} {rewritten}".rstrip() if prefix else f"{indent}{rewritten}"
            changed = True
        index += 1

    if not has_variable and first_variable is not None:
        lines[start + 1] = f"{lines[start + 1].rstrip()} +0 {first_variable}"
        changed = True
    if changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return constant


def _is_section_line(stripped: str) -> bool:
    """True for the words that end the objective and open the next LP section."""
    lowered = stripped.lower()
    return any(
        lowered == word or lowered.startswith(f"{word} ")
        for word in ("subject", "such", "st", "s.t.", "bounds", "binaries", "generals", "end")
    )


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


#: Absolute paths, POSIX and Windows. The solvers echo the temp file they were
#: given, so their own output names the server's filesystem.
#: The lookbehind is what keeps this off ordinary prose: without it the slash
#: in "ratio 3/4" starts a match and the sentence comes back as "ratio 4".
_ABSOLUTE_PATH = re.compile(r"(?<![\w.\-~])(?:[A-Za-z]:)?[\\/](?:[\w.\-~]+[\\/])*[\w.\-~]+")


def scrub_paths(text: str) -> str:
    """Replace absolute paths with the file's own name.

    The solvers are handed a temp file and print its full path back — in the
    verdict line, in parse errors, in whatever they send to stderr. That text
    ends up in ``error_message``, which the comparison table shows to whoever
    ran the comparison, so the server's directory layout was on their screen.

    The basename is kept because the message often needs it to make sense
    ("cannot read model.lp"), and it gives nothing away.
    """

    def keep_the_name(match: "re.Match[str]") -> str:
        return match.group(0).replace("\\", "/").rsplit("/", 1)[-1] or "file"

    return _ABSOLUTE_PATH.sub(keep_the_name, text)


def tail(text: str, *, lines: int = 12, max_chars: int = 1200) -> str:
    """The last few lines of solver output, for an error message.

    A failing solver can print hundreds of lines. The reason is always at the
    end, and the whole log on a user's screen is what the comparison page
    already had to be fixed for once. Paths are scrubbed: this text is shown to
    a user, and the full output is in the log either way.
    """
    trimmed = "\n".join(text.strip().splitlines()[-lines:])
    if len(trimmed) > max_chars:
        trimmed = trimmed[-max_chars:]
    return scrub_paths(trimmed)
