"""One fingerprint of a generated model, shared by the template gates.

Two suites need the same thing: a string that changes when anything about the
model changes. ``test_template_model_quality`` uses it to ask whether changing
one input number moves the model; ``test_template_form_contract`` uses it to ask
whether dropping a form field does. Both carried a byte-identical copy of this
function, differing only in the docstring.
"""

from __future__ import annotations

import json
from typing import Any


def fingerprint(problem: Any) -> str:
    """Everything about the model that a changed or dropped input could move."""
    return json.dumps(
        {
            "v": [(v.name, v.type.value, v.lower_bound, v.upper_bound) for v in problem.variables],
            "o": (problem.objective.sense.value, problem.objective.expression),
            "c": [(c.name, c.expression) for c in problem.constraints],
        },
        sort_keys=True,
    )
