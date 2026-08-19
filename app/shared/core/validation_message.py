"""Turn a Pydantic failure into something a person can read and act on.

`str(exc)` on a ValidationError is written for whoever is debugging the model,
not for whoever uploaded the file. Pasted into a toast it produced this, live:

    JSON does not match OptimizationProblem schema: 2 validation errors for
    OptimizationProblem variables Field required [type=missing,
    input_value={'name': 'frontend', 'ver...3', 'vitest': '^4.1.9'}}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing

Three things are wrong with it beyond the length. The type codes mean nothing
to a reader. The link sends them to Pydantic's website to understand why THEIR
file was refused. And `input_value` echoes a slice of what they uploaded back
at them, which on a config file is a handful of their own dependency versions
and on something private is worse.

`errors(include_url=False, include_input=False, include_context=False)` drops
all three at the source; what is left is where the problem is and what it is.
"""

from __future__ import annotations

from pydantic import ValidationError

#: How many problems to name before saying "and N more". Past a few, a reader
#: fixes the first ones and re-uploads anyway.
MAX_REPORTED_ERRORS = 3

#: Pydantic writes some messages long. Cut rather than fill a toast.
MAX_ERROR_LENGTH = 160


def readable_validation_problems(
    exc: ValidationError,
    *,
    max_errors: int = MAX_REPORTED_ERRORS,
    max_length: int = MAX_ERROR_LENGTH,
) -> tuple[list[str], int]:
    """Return ``(problems, further)``: readable "where: what" lines, and a count.

    ``further`` is how many problems were left unnamed, so a caller can say
    "and 4 more" instead of implying the list is everything.
    """
    errors = exc.errors(include_url=False, include_input=False, include_context=False)
    problems: list[str] = []
    for error in errors[:max_errors]:
        where = ".".join(str(part) for part in error.get("loc", ())) or "model"
        # "Value error, " is Pydantic restating that a validator raised; the
        # sentence after it is the one the validator actually wrote.
        message = str(error.get("msg", "")).removeprefix("Value error, ")
        if len(message) > max_length:
            message = f"{message[:max_length]}…"
        problems.append(f"{where}: {message}")

    return problems, max(0, len(errors) - max_errors)


def validation_summary(exc: ValidationError, *, prefix: str) -> str:
    """One sentence: *prefix* followed by the problems, semicolon-separated."""
    problems, further = readable_validation_problems(exc)
    if not problems:
        return prefix
    listed = "; ".join(problems)
    if further:
        listed = f"{listed}; and {further} more"
    return f"{prefix} {listed}"


__all__ = [
    "MAX_ERROR_LENGTH",
    "MAX_REPORTED_ERRORS",
    "readable_validation_problems",
    "validation_summary",
]
