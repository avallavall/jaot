"""Tests for LLM error taxonomy — public codes vs internal codes, and the
non-negotiable invariant that internal detail (Anthropic error bodies, stack
traces, token counts, retry state) NEVER reaches SSE events sent to clients.

These are the regression guard for the production bug where
`str(e)` from an Anthropic exception leaked into a chat toast, and for the
"Response too large, retrying with higher limit (32768 tokens)..." message
that surfaced in the streaming indicator.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestLLMErrorCode:
    def test_public_codes_are_accepted_by_public_error(self):
        from app.services.llm.errors import LLMErrorCode, PublicLLMError

        err = PublicLLMError(LLMErrorCode.VALIDATION_FAILED, detail="missing x")
        assert err.code is LLMErrorCode.VALIDATION_FAILED
        assert err.detail == "missing x"

    def test_internal_code_in_public_error_raises(self):
        from app.services.llm.errors import InternalLLMError, LLMErrorCode, PublicLLMError

        with pytest.raises(ValueError, match="not a public code"):
            PublicLLMError(LLMErrorCode.SERVICE_UNAVAILABLE)
        # And the inverse — a public code in InternalLLMError is rejected
        with pytest.raises(ValueError, match="is a public code"):
            InternalLLMError(LLMErrorCode.VALIDATION_FAILED)

    def test_is_public_matches_the_set(self):
        from app.services.llm.errors import LLMErrorCode, is_public

        assert is_public(LLMErrorCode.VALIDATION_FAILED) is True
        assert is_public(LLMErrorCode.CONTENT_MODERATION) is True
        assert is_public(LLMErrorCode.INSUFFICIENT_CREDITS) is True
        assert is_public(LLMErrorCode.PARAMETRIC_UNSUPPORTED) is True
        assert is_public(LLMErrorCode.SERVICE_UNAVAILABLE) is False
        assert is_public(LLMErrorCode.INTERNAL_ERROR) is False


# classify_anthropic_error — maps SDK exceptions to (code, metric kind)


class TestClassifyAnthropicError:
    """The classifier powers the metrics/alerts pipeline. A wrong
    classification means the quota-exhaustion alert never fires or fires
    on the wrong condition, so we pin every branch explicitly."""

    def test_quota_exhausted_detected_by_error_body(self):
        from app.services.llm.errors import LLMErrorCode, classify_anthropic_error

        # Anthropic returns the `credit_balance_too_low` token in the
        # body of a 400 BadRequestError when the platform account runs
        # out of billing — this is the exact signal Alertmanager pages on.
        exc = Exception("Error code: 400 - credit_balance_too_low: Your credit balance is too low")
        code, kind = classify_anthropic_error(exc)
        assert code is LLMErrorCode.SERVICE_UNAVAILABLE
        assert kind == "quota_exhausted"

    def test_rate_limit_error_maps_to_service_unavailable(self):
        import anthropic

        from app.services.llm.errors import LLMErrorCode, classify_anthropic_error

        exc = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
        Exception.__init__(exc, "rate limited")
        code, kind = classify_anthropic_error(exc)
        assert code is LLMErrorCode.SERVICE_UNAVAILABLE
        assert kind == "rate_limit"

    def test_authentication_error_maps_to_auth_failed_kind(self):
        import anthropic

        from app.services.llm.errors import LLMErrorCode, classify_anthropic_error

        exc = anthropic.AuthenticationError.__new__(anthropic.AuthenticationError)
        Exception.__init__(exc, "bad api key")
        code, kind = classify_anthropic_error(exc)
        assert code is LLMErrorCode.SERVICE_UNAVAILABLE
        assert kind == "auth_failed"

    def test_connection_error_maps_to_connection_kind(self):
        import anthropic

        from app.services.llm.errors import LLMErrorCode, classify_anthropic_error

        exc = anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)
        Exception.__init__(exc, "network down")
        code, kind = classify_anthropic_error(exc)
        assert code is LLMErrorCode.SERVICE_UNAVAILABLE
        assert kind == "connection"

    def test_timeout_error_maps_to_timeout_kind(self):
        """APITimeoutError must be caught before APIConnectionError (its parent)."""
        import anthropic

        from app.services.llm.errors import LLMErrorCode, classify_anthropic_error

        timeout_cls = getattr(anthropic, "APITimeoutError", None)
        if timeout_cls is None:
            pytest.skip("anthropic SDK lacks APITimeoutError")
        exc = timeout_cls.__new__(timeout_cls)
        Exception.__init__(exc, "request timed out")
        code, kind = classify_anthropic_error(exc)
        assert code is LLMErrorCode.SERVICE_UNAVAILABLE
        assert kind == "timeout"

    def test_api_status_529_maps_to_overloaded(self):
        import anthropic

        from app.services.llm.errors import LLMErrorCode, classify_anthropic_error

        exc = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
        Exception.__init__(exc, "overloaded")
        object.__setattr__(exc, "status_code", 529)
        code, kind = classify_anthropic_error(exc)
        assert code is LLMErrorCode.SERVICE_UNAVAILABLE
        assert kind == "overloaded"

    def test_api_status_408_maps_to_timeout(self):
        import anthropic

        from app.services.llm.errors import LLMErrorCode, classify_anthropic_error

        exc = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
        Exception.__init__(exc, "request timeout")
        object.__setattr__(exc, "status_code", 408)
        code, kind = classify_anthropic_error(exc)
        assert code is LLMErrorCode.SERVICE_UNAVAILABLE
        assert kind == "timeout"

    def test_api_status_generic_maps_to_api_error(self):
        import anthropic

        from app.services.llm.errors import LLMErrorCode, classify_anthropic_error

        exc = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
        Exception.__init__(exc, "server error")
        object.__setattr__(exc, "status_code", 500)
        code, kind = classify_anthropic_error(exc)
        assert code is LLMErrorCode.SERVICE_UNAVAILABLE
        assert kind == "api_error"

    def test_unknown_exception_maps_to_internal_error(self):
        from app.services.llm.errors import LLMErrorCode, classify_anthropic_error

        exc = RuntimeError("unexpected crash in parser")
        code, kind = classify_anthropic_error(exc)
        assert code is LLMErrorCode.INTERNAL_ERROR
        assert kind == "unexpected"


# Leakage prevention — the whole point of this module


class _Delta:
    def __init__(self, text=None, delta_type="text_delta", stop_reason=None):
        self.type = delta_type
        self.text = text
        self.stop_reason = stop_reason


class _Event:
    def __init__(self, event_type, delta=None):
        self.type = event_type
        self.delta = delta


class _StreamContext:
    def __init__(self, events=None, raise_on_enter=None):
        self.events = events or []
        self.raise_on_enter = raise_on_enter

    async def __aenter__(self):
        if self.raise_on_enter is not None:
            raise self.raise_on_enter
        return self

    async def __aexit__(self, *args):
        return None

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for e in self.events:
            yield e


# The secret-like strings we want to prove NEVER end up in a client event.
# These mimic the shapes real Anthropic errors take: full error bodies,
# retry state with token counts, API key fragments, and internal
# implementation detail like stream phase names.
_SECRET_NEEDLES = [
    # Credentials / auth material
    "sk-ant-api",
    "Bearer sk-",
    "x-api-key",
    "ANTHROPIC_API_KEY",
    # Anthropic error body tokens (both top-level type and body message)
    "credit_balance_too_low",
    "insufficient_quota",
    "invalid_api_key",
    "authentication_error",
    "permission_error",
    "rate_limit_exceeded",
    "overloaded_error",
    "api_error",
    "not_found_error",
    "context_length_exceeded",
    # Python internals / stack traces
    "Traceback",
    "stack trace",
    'File "/app/',
    "exc_info",
    # Pre-refactor leaked status strings
    "Response too large",
    "retrying with higher limit",
    "32768 tokens",
    "Anthropic API error",
    "chunk_progress",
    "phase=",
    # Internal stream metadata
    "max_tokens",
    "stop_reason",
    "budget_tokens",
    # Tenant / identity leakage
    "organization_id",
]


def _assert_error_event_shape(err: dict) -> None:
    """Every error event must only carry {type, code, request_id}."""
    allowed = {"type", "code", "request_id"}
    extra = set(err.keys()) - allowed
    assert not extra, f"error event has forbidden fields: {extra}"


def _assert_no_leaks(events: list[dict]) -> None:
    """Hard assertion: no client-facing event field contains internal detail.

    Iterates every event in the list and checks every string value for
    any of the known-leak needles. Only the ``accumulated_text`` field on
    the internal ``truncation_warning`` marker is exempted — that event
    is consumed inside the resilient wrapper and never serialized to SSE.
    """
    serialized = []
    for event in events:
        if event.get("type") == "truncation_warning":
            # Internal marker — never reaches the client, skip.
            continue
        # The ``data`` key on formulation / partial_result events carries
        # user-facing content we do want the user to see (the formulation
        # they asked for); we only scan metadata/status/error fields.
        scannable = {
            k: v for k, v in event.items() if k not in {"data", "text", "accumulated_text"}
        }
        serialized.append(json.dumps(scannable, default=str))
    payload = "\n".join(serialized)
    for needle in _SECRET_NEEDLES:
        assert needle not in payload, (
            f"LEAKAGE DETECTED: {needle!r} appeared in client-facing event payload.\n"
            f"Payload: {payload}"
        )


class TestNoLeakageOnAnthropicFailure:
    """Streaming must never surface raw upstream detail to clients.

    Each scenario stubs the Anthropic client with a different failure mode
    and asserts that (a) the error event carries a stable :class:`LLMErrorCode`,
    and (b) none of the known internal-detail strings appear in any
    client-facing event.
    """

    @pytest.mark.asyncio
    async def test_anthropic_rate_limit_does_not_leak(self):
        import anthropic

        from app.services.llm.errors import LLMErrorCode
        from app.services.llm.formulation_service import generate_formulation

        leaky_exc = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
        Exception.__init__(
            leaky_exc,
            "Error code: 429 - rate_limit_exceeded: Bearer sk-ant-api03-xxx exhausted",
        )
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(
            return_value=_StreamContext(raise_on_enter=leaky_exc)
        )

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            events = []
            async for event in generate_formulation(
                [{"role": "user", "content": "test"}], "claude-sonnet-4-6"
            ):
                events.append(event)

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["code"] is LLMErrorCode.SERVICE_UNAVAILABLE
        # The classic regression: "message" used to carry str(e) and leak
        # the full rate-limit body including the API key fragment.
        assert "message" not in error_events[0]
        _assert_no_leaks(events)

    @pytest.mark.asyncio
    async def test_anthropic_quota_exhausted_does_not_leak(self):
        """Quota exhaustion returns service_unavailable to the user and
        is classified as ``quota_exhausted`` internally so Alertmanager
        can page the admin to top up billing."""
        from app.services.llm.errors import LLMErrorCode
        from app.services.llm.formulation_service import generate_formulation

        leaky_exc = Exception(
            "Error code: 400 - credit_balance_too_low: "
            "Your credit balance is too low to access the Claude API"
        )
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(
            return_value=_StreamContext(raise_on_enter=leaky_exc)
        )

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            events = []
            async for event in generate_formulation(
                [{"role": "user", "content": "test"}], "claude-sonnet-4-6"
            ):
                events.append(event)

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        # User sees a generic "service unavailable" — never "your platform's
        # credit balance is too low", which would leak billing state.
        assert error_events[0]["code"] is LLMErrorCode.SERVICE_UNAVAILABLE
        _assert_no_leaks(events)

    @pytest.mark.asyncio
    async def test_unexpected_exception_maps_to_internal_error(self):
        from app.services.llm.errors import LLMErrorCode
        from app.services.llm.formulation_service import generate_formulation

        leaky_exc = RuntimeError(
            "Traceback (most recent call last):\n"
            '  File "/app/services/llm/formulation_service.py", line 200\n'
            "    crashed with secret=sk-ant-api03-real-key-fragment"
        )
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(
            return_value=_StreamContext(raise_on_enter=leaky_exc)
        )

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            events = []
            async for event in generate_formulation(
                [{"role": "user", "content": "test"}], "claude-sonnet-4-6"
            ):
                events.append(event)

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["code"] is LLMErrorCode.INTERNAL_ERROR
        _assert_no_leaks(events)

    @pytest.mark.asyncio
    async def test_truncation_retry_emits_code_not_message(self):
        """The original bug: the retry status event showed
        'Response too large, retrying with higher limit (32768 tokens)...'
        to the user. After the refactor it must emit only a stable code
        with zero token-count or phase detail."""
        from app.services.llm.formulation_service import generate_formulation_resilient

        # Truncated events cause the resilient wrapper to schedule a retry
        # AND emit a status event. We only need the truncated response to
        # fire the retry branch once — the second attempt can fail the
        # same way, we just want to observe the status event.
        truncated_events = [
            _Event(
                "content_block_delta",
                _Delta(text='{"problem_name": "x", "variables": [{"name": "x"'),
            ),
            _Event("message_delta", _Delta(stop_reason="max_tokens")),
        ]
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(
            side_effect=lambda **kwargs: _StreamContext(events=truncated_events)
        )
        # Chunked fallback client (called when retries exhaust) — return
        # a valid-looking chunk so the generator exits cleanly.
        variables_json = json.dumps(
            {
                "problem_name": "x",
                "summary": "s",
                "variables": [
                    {
                        "name": "x",
                        "type": "continuous",
                        "lower_bound": 0,
                        "upper_bound": 1,
                        "description": "v",
                    }
                ],
                "objective": {"sense": "minimize", "expression": "x", "description": "d"},
            }
        )
        constraints_json = json.dumps(
            {"constraints": [{"name": "c", "expression": "x <= 1", "description": "d"}]}
        )
        chunk_counter = 0

        async def create_side_effect(**kwargs):
            nonlocal chunk_counter
            chunk_counter += 1
            mock_resp = MagicMock()
            if chunk_counter <= 1:
                mock_resp.content = [MagicMock(text=variables_json)]
            else:
                mock_resp.content = [MagicMock(text=constraints_json)]
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
            events = []
            async for event in generate_formulation_resilient(
                [{"role": "user", "content": "test"}],
                "claude-sonnet-4-6",
                user_message="minimize x",
            ):
                events.append(event)

        status_events = [e for e in events if e["type"] == "status"]
        assert status_events, "expected at least one status event from the retry branch"
        # Every status event carries a code and NO message field — this
        # is the exact invariant that broke before the refactor.
        for e in status_events:
            assert "code" in e, f"status event missing code: {e}"
            assert "message" not in e, f"status event leaked a message field: {e}"
            assert "phase" not in e, f"status event leaked a phase field: {e}"
        _assert_no_leaks(events)
