"""Tests for LLM token resilience: estimation, truncation detection, retry, chunked generation.

Covers requirements: LLM-11 through LLM-16.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTokenEstimation:
    """Tests for token estimation, output estimation, and truncation."""

    def test_estimate_tokens_empty(self):
        from app.services.llm.token_estimation import estimate_tokens

        assert estimate_tokens("") == 1

    def test_estimate_tokens_long_string(self):
        from app.services.llm.token_estimation import estimate_tokens

        text = "a" * 400
        assert estimate_tokens(text) == 101

    def test_estimate_output_tokens_floor(self, db_session):
        from app.services.llm.token_estimation import estimate_output_tokens

        result = estimate_output_tokens("simple knapsack with 5 items", db=db_session)
        # Documented minimum floor is 16384 tokens regardless of PSS overrides
        assert result >= 16384

    def test_estimate_output_tokens_medium_problem(self, db_session):
        from app.services.llm.token_estimation import estimate_output_tokens
        from app.services.platform_settings_service import (
            PlatformSettingsService as PSS,
        )

        floor = PSS.get_int(db_session, "LLM_MAX_TOKENS")
        # 150 items pushes the heuristic above the 16384-token floor:
        # 500 + 150 * 40 + (150 * 3) * 30 = 20000 > 16384
        result = estimate_output_tokens(
            "I need to schedule 150 employees across 5 shifts",
            db=db_session,
        )
        # Strict greater-than: scaling logic must kick in (regression guard
        # against an empty filter list collapsing back to the floor)
        assert result > floor

    def test_estimate_output_tokens_large_problem(self, db_session):
        from app.services.llm.token_estimation import estimate_output_tokens
        from app.services.platform_settings_service import (
            PlatformSettingsService as PSS,
        )

        max_tokens = PSS.get_int(db_session, "LLM_MAX_TOKENS")
        result = estimate_output_tokens(
            "Optimize a portfolio with 200 stocks",
            db=db_session,
        )
        assert result > max_tokens

    def test_estimate_output_tokens_no_numbers(self, db_session):
        from app.services.llm.token_estimation import estimate_output_tokens
        from app.services.platform_settings_service import (
            PlatformSettingsService as PSS,
        )

        max_tokens = PSS.get_int(db_session, "LLM_MAX_TOKENS")
        result = estimate_output_tokens("minimize cost", db=db_session)
        assert result == max_tokens

    def test_is_json_incomplete_valid(self):
        from app.services.llm.token_estimation import is_json_incomplete

        assert is_json_incomplete('{"a": 1}') is False

    def test_is_json_incomplete_missing_brace(self):
        from app.services.llm.token_estimation import is_json_incomplete

        assert is_json_incomplete('{"a": 1') is True

    def test_is_json_incomplete_missing_bracket_and_brace(self):
        from app.services.llm.token_estimation import is_json_incomplete

        assert is_json_incomplete('{"a": [1, 2') is True

    def test_is_json_incomplete_empty(self):
        from app.services.llm.token_estimation import is_json_incomplete

        assert is_json_incomplete("") is True

    def test_is_json_incomplete_nested(self):
        from app.services.llm.token_estimation import is_json_incomplete

        assert is_json_incomplete('{"a": {"b": 1}}') is False


VALID_FORMULATION = {
    "problem_name": "Test",
    "summary": "Test problem",
    "variables": [
        {
            "name": "x",
            "type": "continuous",
            "lower_bound": 0,
            "upper_bound": 10,
            "description": "var x",
        },
    ],
    "constraints": [
        {"name": "c1", "expression": "x <= 10", "description": "limit"},
    ],
    "objective": {"sense": "minimize", "expression": "x", "description": "min x"},
}

VALID_FORMULATION_JSON = json.dumps(VALID_FORMULATION)


class TestTokenBudgetTruncation:
    """Tests for token-budget-aware build_messages."""

    def test_short_history_all_included(self):
        """Strengthened TA-04 (12.4 Plan 05 MEDIUM): assert ID + order + content per msg.

        Before: only  (count-only T3).
        After: assert each kept message preserves role+content AND that the new
        user message appears LAST with the expected payload. Plus edge:
        empty history returns a list containing only the new user message.
        """
        from app.services.llm.prompt_templates import build_messages

        history = [
            {"role": "user", "content": "msg 1"},
            {"role": "assistant", "content": "reply 1"},
        ]
        msgs = build_messages(history, "new message")

        # Count preserved.
        assert len(msgs) == 3

        # Per-message role+content match the expected set AND order.
        expected = [
            {"role": "user", "content": "msg 1"},
            {"role": "assistant", "content": "reply 1"},
            {"role": "user", "content": "new message"},
        ]
        assert msgs == expected, (
            f"build_messages dropped/reordered/mutated entries: got {msgs!r}, expected {expected!r}"
        )

        # Edge: empty history must still return just the new user message.
        empty_result = build_messages([], "only message")
        assert empty_result == [{"role": "user", "content": "only message"}]

    def test_long_history_trimmed_by_budget(self):
        from app.services.llm.prompt_templates import build_messages

        # 20 messages, each 200 chars exactly → estimate_tokens = 200//4 + 1 = 51 tokens each.
        # Budget 200 tokens minus 1 for new message = 199 remaining.
        # First 3 msgs cost 51 each = 153, next would push to 204 → stop.
        # Expected kept: 3 history + 1 new = 4 messages.
        history = [
            {"role": "user", "content": f"msg{i:02d} " + ("X" * (200 - 6))} for i in range(20)
        ]
        msgs = build_messages(history, "new", max_history_tokens=200)
        # Exact count: 3 most-recent history + 1 new user message
        assert len(msgs) == 4
        # The kept messages are the most recent 3 (msgs 17, 18, 19) plus the new
        assert msgs[0]["content"].startswith("msg17 ")
        assert msgs[1]["content"].startswith("msg18 ")
        assert msgs[2]["content"].startswith("msg19 ")
        assert msgs[3]["role"] == "user"
        assert msgs[3]["content"] == "new"

    def test_formulation_injection_still_works(self):
        from app.services.llm.prompt_templates import build_messages

        history = [{"role": "user", "content": "hello"}]
        formulation = {"problem_name": "test"}
        msgs = build_messages(history, "refine", latest_formulation=formulation)
        # History (1) + injected assistant (1) + new user (1) = 3
        assert len(msgs) == 3
        assert msgs[1]["role"] == "assistant"
        assert "Current formulation:" in msgs[1]["content"]

    def test_backward_compat_max_history_param(self):
        """max_history still works for backward compatibility."""
        from app.services.llm.prompt_templates import build_messages

        history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        msgs = build_messages(history, "new", max_history=5)
        # Truncated (5) + new user (1) = 6
        assert len(msgs) == 6


class _MockDelta:
    def __init__(self, text=None, delta_type="text_delta", stop_reason=None):
        self.type = delta_type
        self.text = text
        self.stop_reason = stop_reason


class _MockEvent:
    def __init__(self, event_type, delta=None):
        self.type = event_type
        self.delta = delta


class MockStreamContext:
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


def _make_truncated_stream_events():
    """Simulate stream that gets truncated (stop_reason=max_tokens)."""
    incomplete_json = '{"problem_name": "Test", "summary": "Test", "variables": [{"name": "x"'
    events = [
        _MockEvent("content_block_delta", _MockDelta(text=incomplete_json)),
        _MockEvent("message_delta", _MockDelta(stop_reason="max_tokens")),
    ]
    return events


def _make_complete_stream_events():
    """Simulate stream that completes normally."""
    events = [
        _MockEvent("content_block_delta", _MockDelta(text=VALID_FORMULATION_JSON)),
        _MockEvent("message_delta", _MockDelta(stop_reason="end_turn")),
    ]
    return events


class TestTruncationDetection:
    """Tests for stop_reason detection and truncation_warning event."""

    @pytest.mark.asyncio
    async def test_truncation_detected_yields_warning(self):
        """When stop_reason=max_tokens AND JSON incomplete, yield truncation_warning."""
        mock_events = _make_truncated_stream_events()
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=MockStreamContext(mock_events))

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            from app.services.llm.formulation_service import generate_formulation

            events = []
            async for event in generate_formulation(
                [{"role": "user", "content": "test"}], "claude-sonnet-4-6"
            ):
                events.append(event)

        event_types = [e["type"] for e in events]
        assert "truncation_warning" in event_types

    @pytest.mark.asyncio
    async def test_complete_stream_no_warning(self):
        """Normal completion yields formulation, not truncation_warning."""
        mock_events = _make_complete_stream_events()
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=MockStreamContext(mock_events))

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            from app.services.llm.formulation_service import generate_formulation

            events = []
            async for event in generate_formulation(
                [{"role": "user", "content": "test"}], "claude-sonnet-4-6"
            ):
                events.append(event)

        event_types = [e["type"] for e in events]
        assert "formulation" in event_types
        assert "truncation_warning" not in event_types


class TestAutoRetry:
    """Tests for generate_formulation_resilient retry behavior."""

    @pytest.mark.asyncio
    async def test_resilient_success_first_try(self):
        """No retry needed when first attempt succeeds."""
        mock_events = _make_complete_stream_events()
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=MockStreamContext(mock_events))

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            from app.services.llm.formulation_service import generate_formulation_resilient

            events = []
            async for event in generate_formulation_resilient(
                [{"role": "user", "content": "test"}],
                "claude-sonnet-4-6",
                user_message="minimize cost of 5 items",
            ):
                events.append(event)

        event_types = [e["type"] for e in events]
        assert "formulation" in event_types
        assert "done" in event_types
        assert "status" not in event_types  # no retry needed

    @pytest.mark.asyncio
    async def test_resilient_retries_on_truncation(self):
        """Retries with doubled max_tokens when truncated, succeeds on retry."""
        truncated = _make_truncated_stream_events()
        complete = _make_complete_stream_events()

        call_count = 0

        def stream_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MockStreamContext(truncated)
            return MockStreamContext(complete)

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(side_effect=stream_side_effect)

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            from app.services.llm.formulation_service import generate_formulation_resilient

            events = []
            async for event in generate_formulation_resilient(
                [{"role": "user", "content": "test"}],
                "claude-sonnet-4-6",
                user_message="schedule 50 employees",
            ):
                events.append(event)

        event_types = [e["type"] for e in events]
        assert "formulation" in event_types
        assert "status" in event_types  # retry status event
        assert call_count == 2
        # Critical: the status event must carry a stable code, not a raw
        # string — regression guard for the leaked "Response too large..."
        # message that surfaced to the chat UI before the refactor.
        status_events = [e for e in events if e["type"] == "status"]
        assert all("code" in e for e in status_events)
        assert all("message" not in e for e in status_events)

    @pytest.mark.asyncio
    async def test_resilient_exhausts_retries_falls_to_chunked(self, db_session):
        """After exact retry budget exhausted, falls through to chunked generation."""
        from app.services.platform_settings_service import (
            PlatformSettingsService as PSS,
        )

        max_retries = PSS.get_int(db_session, "LLM_MAX_RETRIES")
        expected_stream_calls = 1 + max_retries  # original attempt + N retries

        mock_client = MagicMock()
        # Always return truncated for streaming
        mock_client.messages.stream = MagicMock(
            side_effect=lambda **kwargs: MockStreamContext(_make_truncated_stream_events())
        )

        # Mock chunked generation (non-streaming create)
        vars_response = json.dumps(
            {
                "problem_name": "Test",
                "summary": "A test",
                "variables": [
                    {
                        "name": "x",
                        "type": "continuous",
                        "lower_bound": 0,
                        "upper_bound": 10,
                        "description": "var",
                    }
                ],
                "objective": {"sense": "minimize", "expression": "x", "description": "min x"},
            }
        )
        constraints_response = json.dumps(
            {
                "constraints": [{"name": "c1", "expression": "x <= 10", "description": "limit"}],
            }
        )
        chunk_call = 0

        async def create_side_effect(**kwargs):
            nonlocal chunk_call
            chunk_call += 1
            mock_resp = MagicMock()
            if chunk_call <= 1:
                mock_resp.content = [MagicMock(text=vars_response)]
            else:
                mock_resp.content = [MagicMock(text=constraints_response)]
            return mock_resp

        mock_client.messages.create = AsyncMock(side_effect=create_side_effect)

        with (
            patch(
                "app.services.llm.formulation_service.get_anthropic_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.llm.chunked_generation.get_anthropic_client",
                return_value=mock_client,
            ),
        ):
            from app.services.llm.formulation_service import generate_formulation_resilient

            events = []
            async for event in generate_formulation_resilient(
                [{"role": "user", "content": "test"}],
                "claude-sonnet-4-6",
                user_message="schedule 200 employees",
                db=db_session,
            ):
                events.append(event)

        event_types = [e["type"] for e in events]
        # Stream was attempted exactly 1 + LLM_MAX_RETRIES times before fallthrough
        assert mock_client.messages.stream.call_count == expected_stream_calls
        # Chunked path was actually invoked (variables + constraints chunks = 2 calls)
        assert mock_client.messages.create.call_count >= 2
        assert "status" in event_types
        # The chunked path produces a complete formulation (not partial), since
        # both vars and constraints mocks return valid JSON
        assert "formulation" in event_types
        assert "done" in event_types


class TestChunkedGeneration:
    """Tests for chunked generation schemas and assembly."""

    def test_chunk_schemas_have_additional_properties_false(self):
        from app.schemas.llm import CONSTRAINTS_CHUNK_SCHEMA, VARIABLES_CHUNK_SCHEMA

        assert VARIABLES_CHUNK_SCHEMA.get("additionalProperties") is False
        assert CONSTRAINTS_CHUNK_SCHEMA.get("additionalProperties") is False

    def test_assemble_formulation_both_chunks(self):
        from app.services.llm.chunked_generation import _assemble_formulation

        vars_chunk = {
            "problem_name": "Test",
            "summary": "A test",
            "variables": [
                {
                    "name": "x",
                    "type": "continuous",
                    "lower_bound": 0,
                    "upper_bound": 10,
                    "description": "var",
                }
            ],
            "objective": {"sense": "minimize", "expression": "x", "description": "min x"},
        }
        constraints_chunk = {
            "constraints": [{"name": "c1", "expression": "x <= 10", "description": "limit"}],
        }
        result = _assemble_formulation(vars_chunk, constraints_chunk)
        assert result["problem_name"] == "Test"
        assert len(result["constraints"]) == 1
        assert len(result["variables"]) == 1

    def test_assemble_formulation_no_constraints(self):
        from app.services.llm.chunked_generation import _assemble_formulation

        vars_chunk = {
            "problem_name": "Test",
            "summary": "A test",
            "variables": [
                {
                    "name": "x",
                    "type": "continuous",
                    "lower_bound": 0,
                    "upper_bound": 10,
                    "description": "var",
                }
            ],
            "objective": {"sense": "minimize", "expression": "x", "description": "min x"},
        }
        result = _assemble_formulation(vars_chunk, None)
        assert result["constraints"] == []
        assert result["problem_name"] == "Test"

    @pytest.mark.asyncio
    async def test_chunked_generation_yields_progress_events(self):
        """generate_formulation_chunked yields chunk_progress events."""
        from app.services.llm.chunked_generation import generate_formulation_chunked

        vars_response = json.dumps(
            {
                "problem_name": "Test",
                "summary": "A test",
                "variables": [
                    {
                        "name": "x",
                        "type": "continuous",
                        "lower_bound": 0,
                        "upper_bound": 10,
                        "description": "var",
                    }
                ],
                "objective": {"sense": "minimize", "expression": "x", "description": "min x"},
            }
        )
        constraints_response = json.dumps(
            {
                "constraints": [{"name": "c1", "expression": "x <= 10", "description": "limit"}],
            }
        )

        mock_client = MagicMock()
        # _generate_chunk uses client.messages.create (non-streaming)
        mock_response_vars = MagicMock()
        mock_response_vars.content = [MagicMock(text=vars_response)]
        mock_response_constraints = MagicMock()
        mock_response_constraints.content = [MagicMock(text=constraints_response)]

        call_count = 0

        async def create_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return mock_response_vars
            return mock_response_constraints

        mock_client.messages.create = AsyncMock(side_effect=create_side_effect)

        with patch(
            "app.services.llm.chunked_generation.get_anthropic_client",
            return_value=mock_client,
        ):
            events = []
            async for event in generate_formulation_chunked(
                [{"role": "user", "content": "test"}], "claude-sonnet-4-6"
            ):
                events.append(event)

        event_types = [e["type"] for e in events]
        assert "status" in event_types
        assert "formulation" in event_types
        assert "done" in event_types

        # Verify status codes cover each chunked-generation phase. Codes
        # replace the free-form "phase" strings that previously leaked.
        status_codes = [e["code"] for e in events if e["type"] == "status"]
        assert "generating_variables" in status_codes
        assert "generating_constraints" in status_codes
        assert "assembling" in status_codes

    @pytest.mark.asyncio
    async def test_chunked_generation_partial_result_on_constraint_failure(self):
        """When constraints chunk fails, yields partial_result with warning."""
        from app.services.llm.chunked_generation import generate_formulation_chunked

        vars_response = json.dumps(
            {
                "problem_name": "Test",
                "summary": "A test",
                "variables": [
                    {
                        "name": "x",
                        "type": "continuous",
                        "lower_bound": 0,
                        "upper_bound": 10,
                        "description": "var",
                    }
                ],
                "objective": {"sense": "minimize", "expression": "x", "description": "min x"},
            }
        )

        mock_client = MagicMock()
        mock_response_vars = MagicMock()
        mock_response_vars.content = [MagicMock(text=vars_response)]

        call_count = 0

        async def create_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return mock_response_vars
            raise Exception("API error")

        mock_client.messages.create = AsyncMock(side_effect=create_side_effect)

        with patch(
            "app.services.llm.chunked_generation.get_anthropic_client",
            return_value=mock_client,
        ):
            events = []
            async for event in generate_formulation_chunked(
                [{"role": "user", "content": "test"}], "claude-sonnet-4-6"
            ):
                events.append(event)

        event_types = [e["type"] for e in events]
        assert "partial_result" in event_types
        partial = next(e for e in events if e["type"] == "partial_result")
        assert "warning" in partial
        assert partial["data"]["constraints"] == []


class TestGracefulDegradation:
    """Tests for the full escalation ladder ending in chunked generation."""

    @pytest.mark.asyncio
    async def test_resilient_falls_through_to_chunked(self):
        """After retries exhausted, generate_formulation_resilient calls chunked generation.

        Both vars and constraints chunks succeed, so we expect a complete
        'formulation' event (not 'partial_result'). Pinned to one expected
        event instead of an OR cop-out.
        """
        # Always return truncated from generate_formulation
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(
            side_effect=lambda **kwargs: MockStreamContext(_make_truncated_stream_events())
        )

        # Chunked generation succeeds for BOTH variables and constraints
        vars_response = json.dumps(
            {
                "problem_name": "Test",
                "summary": "A test",
                "variables": [
                    {
                        "name": "x",
                        "type": "continuous",
                        "lower_bound": 0,
                        "upper_bound": 10,
                        "description": "var",
                    }
                ],
                "objective": {"sense": "minimize", "expression": "x", "description": "min x"},
            }
        )
        constraints_response = json.dumps(
            {
                "constraints": [{"name": "c1", "expression": "x <= 10", "description": "limit"}],
            }
        )

        mock_response_vars = MagicMock()
        mock_response_vars.content = [MagicMock(text=vars_response)]
        mock_response_constraints = MagicMock()
        mock_response_constraints.content = [MagicMock(text=constraints_response)]

        chunk_call = 0

        async def create_side_effect(**kwargs):
            nonlocal chunk_call
            chunk_call += 1
            if chunk_call <= 1:
                return mock_response_vars
            return mock_response_constraints

        mock_client.messages.create = AsyncMock(side_effect=create_side_effect)

        with (
            patch(
                "app.services.llm.formulation_service.get_anthropic_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.llm.chunked_generation.get_anthropic_client",
                return_value=mock_client,
            ),
        ):
            from app.services.llm.formulation_service import generate_formulation_resilient

            events = []
            async for event in generate_formulation_resilient(
                [{"role": "user", "content": "test"}],
                "claude-sonnet-4-6",
                user_message="optimize 200 stocks",
            ):
                events.append(event)

        event_types = [e["type"] for e in events]
        # Chunked generation produced progress events
        assert "status" in event_types
        # Both chunk mocks succeeded → expect a complete formulation, NOT partial
        assert "formulation" in event_types
        assert "partial_result" not in event_types
        assert "done" in event_types

    @pytest.mark.asyncio
    async def test_partial_result_is_valid_formulation(self):
        """Partial result from graceful degradation is a valid Formulation."""
        from app.schemas.llm import Formulation
        from app.services.llm.chunked_generation import _assemble_formulation

        vars_chunk = {
            "problem_name": "Test",
            "summary": "A test",
            "variables": [
                {
                    "name": "x",
                    "type": "continuous",
                    "lower_bound": 0,
                    "upper_bound": 10,
                    "description": "var",
                }
            ],
            "objective": {"sense": "minimize", "expression": "x", "description": "min x"},
        }
        result = _assemble_formulation(vars_chunk, None)
        # Should be valid Pydantic model
        f = Formulation.model_validate(result)
        assert f.problem_name == "Test"
        assert f.constraints == []
