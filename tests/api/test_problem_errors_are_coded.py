"""An invalid problem is refused with a code a page can translate.

The custom solve page printed the API's English as it came: "Constraint c1
references undefined variables: {'q'}" (a Python set) and "Constraint c1 cannot
be parsed: EXPR_PARSE_ERROR: Unexpected token '*' at position 5" (the parser's
own diagnostic), in every locale. The English ``detail`` stays as it was for
API and MCP clients; the code and its parameters are what the page renders.

# CONTRACT-TEST: every validation issue carries a code with words in en.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _problem(**overrides) -> dict:
    problem = {
        "name": "coded_errors",
        "variables": [
            {"name": "x", "type": "integer", "lower_bound": 0, "upper_bound": 10},
            {"name": "y", "type": "integer", "lower_bound": 0, "upper_bound": 10},
        ],
        "objective": {"expression": "x + y", "sense": "maximize"},
        "constraints": [{"name": "c1", "expression": "x + y <= 3"}],
    }
    problem.update(overrides)
    return problem


class TestSolveRefusal:
    def test_an_undeclared_variable_names_the_constraint_and_the_variable(
        self, authenticated_client
    ) -> None:
        body = _problem(constraints=[{"name": "c1", "expression": "x + q <= 3"}])

        res = authenticated_client.post("/api/v2/solve", json=body)

        assert res.status_code == 400, res.text
        payload = res.json()
        assert payload["code"] == "problem.constraint_undefined_variables"
        assert payload["params"] == {"constraint": "c1", "names": "q"}
        # The English detail is the API contract and did not change.
        assert payload["detail"] == "Constraint c1 references undefined variables: {'q'}"

    def test_an_unreadable_constraint_says_which_one(self, authenticated_client) -> None:
        body = _problem(constraints=[{"name": "c1", "expression": "2*x +* y <= 3"}])

        res = authenticated_client.post("/api/v2/solve", json=body)

        assert res.status_code == 400, res.text
        assert res.json()["code"] == "problem.constraint_unreadable"
        assert res.json()["params"] == {"constraint": "c1"}


class TestValidateEndpoint:
    def test_every_error_comes_with_its_code(self, authenticated_client) -> None:
        body = _problem(
            objective={"expression": "x + z", "sense": "maximize"},
            constraints=[{"name": "c1", "expression": "2*x +* y <= 3"}],
        )

        res = authenticated_client.post("/api/v2/solve/validate", json=body)

        assert res.status_code == 200, res.text
        payload = res.json()
        assert payload["valid"] is False
        assert [i["code"] for i in payload["issues"]] == [
            "problem.objective_undefined_variables",
            "problem.constraint_unreadable",
        ]
        assert payload["issues"][0]["params"] == {"names": "z"}
        assert [i["message"] for i in payload["issues"]] == payload["errors"]

    def test_a_valid_problem_has_no_issues(self, authenticated_client) -> None:
        res = authenticated_client.post("/api/v2/solve/validate", json=_problem())

        assert res.status_code == 200, res.text
        assert res.json()["valid"] is True
        assert res.json()["issues"] == []


def test_every_issue_code_has_words() -> None:
    """The codes are built from data, so the CodedHTTPException scan cannot see them."""
    source = (_REPO / "app/domains/solver/services/problem_validation.py").read_text(
        encoding="utf-8"
    )
    codes = set(re.findall(r'code="(problem\.[a-z_]+)"', source))
    codes |= set(
        re.findall(
            r'code="(problem\.[a-z_]+)"',
            (_REPO / "app/api/v2/solve.py").read_text(encoding="utf-8"),
        )
    )
    assert len(codes) >= 8, codes

    catalogue = json.loads((_REPO / "frontend/messages/en.json").read_text(encoding="utf-8"))
    problem_codes = catalogue["errors"]["codes"]["problem"]
    missing = sorted(code for code in codes if code.split(".", 1)[1] not in problem_codes)
    assert missing == []
