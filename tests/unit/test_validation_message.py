"""# CONTRACT-TEST: Pydantic's own wording never reaches a user.

`str(exc)` on a ValidationError was pasted into a toast, live:

    JSON does not match OptimizationProblem schema: 2 validation errors for
    OptimizationProblem variables Field required [type=missing,
    input_value={'name': 'frontend', 'ver...3', 'vitest': '^4.1.9'}}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing

Three things beyond the length: type codes that mean nothing to a reader, a
link sending them to Pydantic's site to learn why THEIR file was refused, and
`input_value` echoing a slice of what they uploaded back at them.
"""

import pytest
from pydantic import ValidationError

from app.schemas.optimization import OptimizationProblem
from app.shared.core.validation_message import (
    readable_validation_problems,
    validation_summary,
)

pytestmark = pytest.mark.unit


def _package_json_shaped() -> ValidationError:
    """The exact case from the sweep: a file that is JSON but not a model."""
    with pytest.raises(ValidationError) as caught:
        OptimizationProblem(
            **{"name": "frontend", "version": "3.6.0", "devDependencies": {"vitest": "^4.1.9"}}
        )
    return caught.value


def test_it_names_where_and_what_without_pydantic_wording():
    problems, further = readable_validation_problems(_package_json_shaped())

    assert problems, "a rejected payload must say something"
    joined = " ".join(problems)
    assert "variables" in joined
    assert "objective" in joined
    # None of the three things that made the original unreadable.
    assert "errors.pydantic.dev" not in joined
    assert "type=missing" not in joined
    assert "input_value" not in joined
    assert further == 0


def test_it_never_echoes_the_payload_back():
    """The uploaded file's own contents must not come back in the message."""
    problems, _ = readable_validation_problems(_package_json_shaped())
    joined = " ".join(problems)

    assert "vitest" not in joined
    assert "devDependencies" not in joined
    assert "3.6.0" not in joined


def test_it_caps_the_list_and_counts_the_rest():
    problems, further = readable_validation_problems(_package_json_shaped(), max_errors=1)

    assert len(problems) == 1
    assert further >= 1


def test_it_cuts_a_long_message_instead_of_filling_a_toast():
    problems, _ = readable_validation_problems(_package_json_shaped(), max_length=10)

    for line in problems:
        _, _, message = line.partition(": ")
        assert len(message) <= 11, line  # 10 plus the ellipsis


def test_the_summary_reads_as_one_sentence():
    summary = validation_summary(
        _package_json_shaped(), prefix="This JSON is not an optimization problem."
    )

    assert summary.startswith("This JSON is not an optimization problem.")
    assert "errors.pydantic.dev" not in summary
    assert "variables" in summary
