"""Tests for the LLM solution-explanation service (P1 — solution explainer).

Covers:
- explain_solution() yields the expected event sequence (status → deltas → done)
- the explanation is grounded: the user turn embeds the exact formulation /
  solution / sensitivity values, and the solution-explanation system prompt is used
- build_solution_explanation_prompt() embeds provided data and is honest about
  missing sensitivity
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.llm.errors import LLMStatusCode
from app.services.llm.prompt_templates import (
    SOLUTION_EXPLANATION_SYSTEM_PROMPT,
    build_solution_explanation_prompt,
)

FORMULATION = {
    "problem_name": "tiny_lp",
    "variables": [{"name": "x", "type": "continuous"}, {"name": "y", "type": "continuous"}],
    "constraints": [{"name": "c1", "expression": "x + y <= 4"}],
    "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
}
SOLUTION = {"objective_value": 9.0, "solution": {"x": 1.0, "y": 3.0}}
SENSITIVITY = {
    "constraints": [{"name": "c1", "shadow_price": 2.0, "is_binding": True}],
    "variables": [{"name": "x", "reduced_cost": 0.0, "is_at_bound": False}],
    "is_approximate": False,
}
# A row the LP relaxation prices at zero while the integer solution saturates it —
# the shape that made the explanation claim nothing was at capacity.
EXACT_ANALYSIS = {
    "objective_value": 34.0,
    "total_constraints": 7,
    "binding_count": 4,
    "constraints": [
        {
            "name": "workload_w2",
            "activity": 2.0,
            "rhs": 2.0,
            "slack": 0.0,
            "is_binding": True,
            "utilization": 1.0,
        },
        {
            "name": "workload_w1",
            "activity": 1.0,
            "rhs": 2.0,
            "slack": 1.0,
            "is_binding": False,
            "utilization": 0.5,
        },
    ],
    "computed": True,
}


def _text_events(text: str):
    """Build mock Anthropic content_block_delta text events."""
    events = []
    for chunk in (text[i : i + 8] for i in range(0, len(text), 8)):
        event = MagicMock()
        event.type = "content_block_delta"
        event.delta = MagicMock()
        event.delta.type = "text_delta"
        event.delta.text = chunk
        events.append(event)
    return events


class _MockStreamContext:
    """Mock async context manager for client.messages.stream()."""

    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for event in self.events:
            yield event


class TestBuildSolutionExplanationPrompt:
    def test_embeds_formulation_solution_and_sensitivity(self):
        prompt = build_solution_explanation_prompt(FORMULATION, SOLUTION, SENSITIVITY)
        assert "tiny_lp" in prompt
        assert "9.0" in prompt
        assert "shadow_price" in prompt
        assert "Sensitivity analysis" in prompt

    def test_states_sensitivity_unavailable_when_missing(self):
        prompt = build_solution_explanation_prompt(FORMULATION, SOLUTION, None)
        assert "Not available" in prompt
        # Never claim sensitivity data that was not supplied.
        assert "shadow_price" not in prompt

    def test_small_solution_is_embedded_in_full(self):
        """A tiny solve keeps the exact values — no sampling, no SAMPLED flag."""
        prompt = build_solution_explanation_prompt(FORMULATION, SOLUTION, SENSITIVITY)
        assert "SAMPLED" not in prompt
        assert "_solution_omitted" not in prompt

    # CONTRACT-TEST: which constraints bind must reach the model from the exact,
    # solution-based analysis. On a MIP the LP relaxation prices binding rows at
    # zero, and a prompt carrying only sensitivity produced explanations stating
    # that a constraint saturated at 2 <= 2 had headroom.
    def test_embeds_the_exact_analysis_when_available(self):
        prompt = build_solution_explanation_prompt(
            FORMULATION, SOLUTION, SENSITIVITY, EXACT_ANALYSIS
        )
        assert "workload_w2" in prompt
        assert "utilization" in prompt
        assert "this is what binds" in prompt
        # The exact block must be read before the relaxation's numbers.
        assert prompt.index("Exact analysis") < prompt.index("Sensitivity analysis")

    def test_forbids_binding_claims_when_exact_analysis_is_missing(self):
        prompt = build_solution_explanation_prompt(FORMULATION, SOLUTION, SENSITIVITY)
        assert "do not state which constraints are binding" in prompt

    def test_system_prompt_denies_the_relaxation_authority_over_binding(self):
        """The prompt must not let a zero shadow price stand in for "has slack"."""
        assert "exact analysis" in SOLUTION_EXPLANATION_SYSTEM_PROMPT.lower()
        assert "LP RELAXATION" in SOLUTION_EXPLANATION_SYSTEM_PROMPT
        assert "NEVER infer" in SOLUTION_EXPLANATION_SYSTEM_PROMPT

    # CONTRACT-TEST: a large solution is SAMPLED so the prompt never blows the context
    # window. A real 10k-variable solve reached 11.6M tokens (> the 1M provider max)
    # because the full variable→value map + variable list were embedded verbatim.
    def test_huge_solution_is_sampled_and_bounded(self):
        from app.services.llm.token_estimation import estimate_tokens

        n = 100  # a 100x100 assignment: 10k variables, mostly zero
        formulation = {
            "variables": [
                {"name": f"x_{i}_{j}", "type": "binary"} for i in range(n) for j in range(n)
            ],
            "constraints": [
                {
                    "name": f"c{i}",
                    "expression": " + ".join(f"x_{i}_{j}" for j in range(n)) + " <= 1",
                }
                for i in range(n)
            ],
            "objective": {"sense": "minimize", "expression": "x_0_0"},
        }
        solution = {
            "objective_value": 42,
            "solver_status": "optimal",
            "solution": {f"x_{i}_{j}": (1 if i == j else 0) for i in range(n) for j in range(n)},
            "variables": [
                {"name": f"x_{i}_{j}", "value": (1 if i == j else 0)}
                for i in range(n)
                for j in range(n)
            ],
        }
        prompt = build_solution_explanation_prompt(formulation, solution, None)
        assert "SAMPLED" in prompt
        # Comfortably under the 1M provider maximum (and the whole point of the fix).
        assert estimate_tokens(prompt) < 200_000
        # The non-zero decisions (the diagonal x_i_i = 1) survive the sampling.
        assert '"x_0_0": 1' in prompt
        assert "_solution_omitted" in prompt

    def test_sampling_keeps_the_largest_decisions(self):
        """The sample is the TOP non-zero decisions by magnitude — a dominant value
        must survive even when thousands of small non-zeros precede it in order."""
        n = 3000
        solution = {
            "objective_value": 1.0,
            "solver_status": "optimal",
            "solution": {f"tiny_variable_{i}": 0.001 for i in range(n)} | {"big": 9999.0},
            "variables": [{"name": f"tiny_variable_{i}", "value": 0.001} for i in range(n)]
            + [{"name": "big", "value": 9999.0}],
        }
        prompt = build_solution_explanation_prompt(None, solution, None)
        assert "SAMPLED" in prompt
        assert '"big": 9999.0' in prompt  # the name→value map keeps the dominant decision
        assert '"name": "big"' in prompt  # …and so does the variables list


class TestExplainSolution:
    @pytest.mark.asyncio
    async def test_yields_status_then_deltas_then_done(self):
        """explain_solution streams: status(EXPLAINING) → delta(s) → done."""
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(
            return_value=_MockStreamContext(_text_events("Make x=1 and y=3 for objective 9."))
        )

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            from app.services.llm.explanation_service import explain_solution

            events = []
            async for event in explain_solution(
                [], FORMULATION, SOLUTION, SENSITIVITY, "claude-sonnet-5"
            ):
                events.append(event)

        types = [e["type"] for e in events]
        # First event is the explaining status with the stable enum code.
        assert events[0]["type"] == "status"
        assert events[0]["code"] == LLMStatusCode.EXPLAINING
        assert "delta" in types
        assert types[-1] == "done"

        streamed = "".join(e.get("text", "") for e in events if e["type"] == "delta")
        assert "objective 9" in streamed

    @pytest.mark.asyncio
    async def test_uses_solution_system_prompt_and_grounded_user_turn(self):
        """The Anthropic call carries the solution system prompt + grounded user turn."""
        captured: dict = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return _MockStreamContext(_text_events("ok"))

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(side_effect=_capture)

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            from app.services.llm.explanation_service import explain_solution

            async for _ in explain_solution(
                [], FORMULATION, SOLUTION, SENSITIVITY, "claude-sonnet-5"
            ):
                pass

        assert captured["system"].startswith(SOLUTION_EXPLANATION_SYSTEM_PROMPT)
        # …followed by the response-language directive every explanation carries.
        assert "## Response language" in captured["system"]
        last_user_turn = captured["messages"][-1]
        assert last_user_turn["role"] == "user"
        # Grounded: the exact objective value and a constraint name are present.
        assert "9.0" in last_user_turn["content"]
        assert "c1" in last_user_turn["content"]

    @pytest.mark.asyncio
    async def test_prior_messages_are_preserved_before_user_turn(self):
        """Existing conversation turns are kept; the grounded turn is appended last."""
        captured: dict = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return _MockStreamContext(_text_events("ok"))

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(side_effect=_capture)

        prior = [{"role": "user", "content": "earlier question"}]
        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            from app.services.llm.explanation_service import explain_solution

            async for _ in explain_solution(prior, FORMULATION, SOLUTION, None, "claude-sonnet-5"):
                pass

        assert captured["messages"][0] == prior[0]
        assert captured["messages"][-1]["role"] == "user"
        assert len(captured["messages"]) == 2
