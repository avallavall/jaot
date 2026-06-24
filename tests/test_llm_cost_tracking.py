"""Tests for real LLM cost tracking + the monthly budget guardrail (W17).

Covers:
- Cost computed from the per-model pricing map (platform setting), with the
  "default" entry as fallback for unknown models.
- Real token usage captured from the (mocked) Anthropic stream and persisted
  on the assistant LLMMessage row (input_tokens / output_tokens / cost_eur).
- Calendar-month cost aggregation + the Prometheus budget gauges.
- The auto-pause gate: over-budget blocks with the friendly
  feature-disabled shape; under-budget passes; budget=0 disables.

The Anthropic client is mocked at the provider boundary (established
pattern from tests/test_llm.py); conversations, messages, settings, and
credits all run against the real PostgreSQL database.
"""

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models.llm_conversation import LLMConversation, LLMMessage
from app.services.llm.cost_tracking import (
    compute_message_cost_eur,
    get_budget_status,
    get_month_cost_eur,
    reset_budget_cache,
)
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

VALID_FORMULATION = {
    "problem_name": "Cost Tracking Probe",
    "summary": "Minimal formulation used to drive the SSE stream.",
    "variables": [
        {
            "name": "x",
            "type": "integer",
            "lower_bound": 0,
            "upper_bound": 10,
            "description": "var x",
        },
    ],
    "constraints": [
        {"name": "c1", "expression": "x <= 5", "description": "cap"},
    ],
    "objective": {"sense": "minimize", "expression": "x", "description": "min x"},
}
VALID_FORMULATION_JSON = json.dumps(VALID_FORMULATION)

# Sonnet rates from the LLM_MODEL_PRICING_EUR_PER_MTOK registry default.
SONNET_IN_RATE = 2.78
SONNET_OUT_RATE = 13.89
INPUT_TOKENS = 1200
OUTPUT_TOKENS = 850
EXPECTED_COST = (INPUT_TOKENS * SONNET_IN_RATE + OUTPUT_TOKENS * SONNET_OUT_RATE) / 1_000_000


@pytest.fixture
def test_conversation(db_session, test_user, test_organization):
    conv = LLMConversation(
        id=generate_id("conv_"),
        organization_id=test_organization.id,
        user_id=test_user.id,
        created_at=utcnow().replace(tzinfo=None),
        expires_at=(utcnow() + timedelta(hours=24)).replace(tzinfo=None),
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    return conv


def _make_stream_events_with_usage(
    text=VALID_FORMULATION_JSON,
    input_tokens=INPUT_TOKENS,
    output_tokens=OUTPUT_TOKENS,
):
    """Mock Anthropic stream: message_start (input usage) + text deltas +
    final message_delta (stop_reason + cumulative output usage)."""
    events = []

    start = MagicMock()
    start.type = "message_start"
    start.message.usage.input_tokens = input_tokens
    events.append(start)

    chunk_size = 80
    for i in range(0, len(text), chunk_size):
        ev = MagicMock()
        ev.type = "content_block_delta"
        ev.delta = MagicMock()
        ev.delta.type = "text_delta"
        ev.delta.text = text[i : i + chunk_size]
        events.append(ev)

    final = MagicMock()
    final.type = "message_delta"
    final.delta.stop_reason = "end_turn"
    final.usage.output_tokens = output_tokens
    events.append(final)
    return events


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


def _mock_anthropic_client(events=None):
    client = MagicMock()
    client.messages.stream = MagicMock(
        return_value=MockStreamContext(events or _make_stream_events_with_usage())
    )
    return client


def _add_costed_message(db_session, conv, cost_eur, created_at=None):
    msg = LLMMessage(
        id=generate_id("msg_"),
        conversation_id=conv.id,
        role="assistant",
        content="costed",
        input_tokens=100,
        output_tokens=100,
        cost_eur=cost_eur,
        created_at=(created_at or utcnow()).replace(tzinfo=None),
    )
    db_session.add(msg)
    db_session.commit()
    return msg


class TestCostComputation:
    """Cost derives from the LLM_MODEL_PRICING_EUR_PER_MTOK map."""

    def test_known_model_uses_its_rates(self, db_session):
        cost = compute_message_cost_eur(db_session, "claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost == pytest.approx(SONNET_IN_RATE + SONNET_OUT_RATE, abs=1e-6)

    def test_unknown_model_falls_back_to_default_entry(self, db_session):
        """Pricing-map fallback: unknown models price at the 'default' entry."""
        cost = compute_message_cost_eur(db_session, "claude-fable-9", 1_000_000, 1_000_000)
        # Registry default entry = Opus rates (conservative over-estimate).
        assert cost == pytest.approx(4.63 + 23.15, abs=1e-6)

    def test_unparseable_pricing_setting_uses_hard_fallback(self, db_session):
        PSS.set(db_session, "LLM_MODEL_PRICING_EUR_PER_MTOK", "{not json")
        db_session.commit()
        cost = compute_message_cost_eur(db_session, "claude-sonnet-4-6", 1_000_000, 0)
        assert cost == pytest.approx(4.63, abs=1e-6)  # hard fallback (Opus input)

    def test_zero_tokens_cost_zero(self, db_session):
        assert compute_message_cost_eur(db_session, "claude-sonnet-4-6", 0, 0) == 0.0


class TestUsageCaptureFromStream:
    """generate_formulation / generate_text_response emit a usage event."""

    @pytest.mark.asyncio
    async def test_generate_formulation_yields_usage_event(self):
        mock_client = _mock_anthropic_client()
        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            from app.services.llm.formulation_service import generate_formulation

            events = []
            async for event in generate_formulation(
                [{"role": "user", "content": "Minimize x"}],
                "claude-sonnet-4-6",
            ):
                events.append(event)

        usage_events = [e for e in events if e["type"] == "usage"]
        assert len(usage_events) == 1
        assert usage_events[0]["model"] == "claude-sonnet-4-6"
        assert usage_events[0]["input_tokens"] == INPUT_TOKENS
        assert usage_events[0]["output_tokens"] == OUTPUT_TOKENS
        # Usage must arrive before done so the endpoint can persist it.
        assert events[-1]["type"] == "done"
        # The formulation still parses (usage capture must not break parsing).
        assert any(e["type"] == "formulation" for e in events)

    @pytest.mark.asyncio
    async def test_generate_text_response_yields_usage_event(self):
        mock_client = _mock_anthropic_client(
            _make_stream_events_with_usage(text="Plain explanation.")
        )
        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            from app.services.llm.formulation_service import generate_text_response

            events = []
            async for event in generate_text_response(
                [{"role": "user", "content": "Why infeasible?"}],
                "claude-sonnet-4-6",
            ):
                events.append(event)

        usage_events = [e for e in events if e["type"] == "usage"]
        assert len(usage_events) == 1
        assert usage_events[0]["input_tokens"] == INPUT_TOKENS
        assert usage_events[0]["output_tokens"] == OUTPUT_TOKENS


class TestUsagePersistence:
    """POST /messages persists real tokens + cost on the assistant message."""

    def test_assistant_message_persists_tokens_and_cost(
        self, authenticated_client, db_session, test_conversation
    ):
        mock_client = _mock_anthropic_client()
        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={"message": "Minimize x subject to x <= 5"},
            )

        assert response.status_code == 200, response.text
        # Internal accounting must never leak into the SSE stream.
        assert "event: usage" not in response.text

        db_session.expire_all()
        assistant_msgs = (
            db_session.query(LLMMessage)
            .filter(
                LLMMessage.conversation_id == test_conversation.id,
                LLMMessage.role == "assistant",
            )
            .all()
        )
        assert len(assistant_msgs) == 1
        msg = assistant_msgs[0]
        assert msg.input_tokens == INPUT_TOKENS
        assert msg.output_tokens == OUTPUT_TOKENS
        assert msg.cost_eur is not None
        assert float(msg.cost_eur) == pytest.approx(EXPECTED_COST, abs=2e-6)

        # User message rows carry NULL usage (nothing was billed for them).
        user_msgs = (
            db_session.query(LLMMessage)
            .filter(
                LLMMessage.conversation_id == test_conversation.id,
                LLMMessage.role == "user",
            )
            .all()
        )
        assert len(user_msgs) == 1
        assert user_msgs[0].cost_eur is None


class TestMonthCostAggregation:
    """Month gauge sums only the current calendar month."""

    def test_month_cost_sums_current_month_only(self, db_session, test_conversation):
        now = utcnow()
        _add_costed_message(db_session, test_conversation, 1.25, created_at=now)
        _add_costed_message(db_session, test_conversation, 0.75, created_at=now)
        # Previous-month row must be excluded from the gauge.
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        _add_costed_message(
            db_session, test_conversation, 99.0, created_at=month_start - timedelta(days=1)
        )
        # NULL-cost rows (pre-migration / user messages) must not break SUM.
        _add_costed_message(db_session, test_conversation, None, created_at=now)

        assert get_month_cost_eur(db_session) == pytest.approx(2.0, abs=1e-6)

    def test_budget_status_reads_setting_and_caches(self, db_session, test_conversation):
        _add_costed_message(db_session, test_conversation, 3.0)
        cost, budget = get_budget_status(db_session)
        assert cost == pytest.approx(3.0, abs=1e-6)
        assert budget == pytest.approx(20.0)  # registry default

        # Cached: a new row is invisible until the TTL expires / cache resets.
        _add_costed_message(db_session, test_conversation, 5.0)
        cost_cached, _ = get_budget_status(db_session)
        assert cost_cached == pytest.approx(3.0, abs=1e-6)

        reset_budget_cache()
        cost_fresh, _ = get_budget_status(db_session)
        assert cost_fresh == pytest.approx(8.0, abs=1e-6)

    def test_prometheus_collector_yields_both_gauges(self, db_session, test_conversation):
        from app.shared.core.llm_budget_metrics import LLMBudgetCollector

        _add_costed_message(db_session, test_conversation, 4.5)

        families = {f.name: f for f in LLMBudgetCollector().collect()}
        assert set(families) == {"jaot_llm_cost_eur_month", "jaot_llm_budget_eur"}
        cost_sample = families["jaot_llm_cost_eur_month"].samples[0]
        budget_sample = families["jaot_llm_budget_eur"].samples[0]
        assert cost_sample.value == pytest.approx(4.5, abs=1e-6)
        assert budget_sample.value == pytest.approx(20.0)


class TestBudgetGuardrail:
    """Auto-pause: over-budget blocks gracefully, under-budget passes."""

    def test_over_budget_blocks_with_friendly_feature_disabled_shape(
        self, authenticated_client, db_session, test_conversation, test_organization
    ):
        PSS.set(db_session, "LLM_MONTHLY_BUDGET_EUR", "0.05")
        db_session.commit()
        _add_costed_message(db_session, test_conversation, 0.10)

        balance_before = test_organization.credits_balance
        response = authenticated_client.post(
            f"/api/v2/llm/conversations/{test_conversation.id}/messages",
            json={"message": "Minimize x"},
        )

        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["error"] == "feature_not_available"
        assert detail["reason"] == "llm_monthly_budget_exhausted"
        assert "budget" in detail["message"].lower()

        # Blocked BEFORE pre-pay and BEFORE persisting the user message.
        db_session.expire_all()
        db_session.refresh(test_organization)
        assert test_organization.credits_balance == balance_before
        user_msgs = (
            db_session.query(LLMMessage)
            .filter(
                LLMMessage.conversation_id == test_conversation.id,
                LLMMessage.role == "user",
            )
            .count()
        )
        assert user_msgs == 0

    def test_under_budget_passes_through(self, authenticated_client, db_session, test_conversation):
        # Spend well under the 20 EUR default budget.
        _add_costed_message(db_session, test_conversation, 1.0)

        mock_client = _mock_anthropic_client()
        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={"message": "Minimize x"},
            )

        assert response.status_code == 200, response.text
        assert "event: done" in response.text

    def test_budget_zero_disables_guardrail(
        self, authenticated_client, db_session, test_conversation
    ):
        PSS.set(db_session, "LLM_MONTHLY_BUDGET_EUR", "0")
        db_session.commit()
        _add_costed_message(db_session, test_conversation, 500.0)

        mock_client = _mock_anthropic_client()
        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=mock_client,
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={"message": "Minimize x"},
            )

        assert response.status_code == 200, response.text
