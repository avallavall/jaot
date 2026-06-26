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
                [], FORMULATION, SOLUTION, SENSITIVITY, "claude-sonnet-4-6"
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
                [], FORMULATION, SOLUTION, SENSITIVITY, "claude-sonnet-4-6"
            ):
                pass

        assert captured["system"] == SOLUTION_EXPLANATION_SYSTEM_PROMPT
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

            async for _ in explain_solution(
                prior, FORMULATION, SOLUTION, None, "claude-sonnet-4-6"
            ):
                pass

        assert captured["messages"][0] == prior[0]
        assert captured["messages"][-1]["role"] == "user"
        assert len(captured["messages"]) == 2
