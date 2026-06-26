"""Guard: a refusal / empty formulation must never overwrite a real model.

Unit-tests ``_is_real_formulation`` (app/api/v2/llm.py), which gates whether a
streamed formulation is persisted as the conversation's current model. Refusals
(``problem_name == "not_applicable"``) and variable-less payloads must be rejected
so a follow-up question can never erase the user's work.
"""

from app.api.v2.llm import _is_real_formulation

_REAL = {
    "problem_name": "production_plan",
    "variables": [{"name": "x", "type": "continuous"}],
    "constraints": [],
    "objective": {"sense": "maximize", "expression": "x"},
}


def test_real_model_is_persisted():
    assert _is_real_formulation(_REAL) is True


def test_refusal_is_rejected():
    refusal = {"problem_name": "not_applicable", "variables": [], "constraints": []}
    assert _is_real_formulation(refusal) is False


def test_variable_less_formulation_is_rejected():
    assert _is_real_formulation({"problem_name": "x", "variables": []}) is False


def test_none_and_empty_are_rejected():
    assert _is_real_formulation(None) is False
    assert _is_real_formulation({}) is False
