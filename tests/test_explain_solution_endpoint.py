"""Tests for POST /llm/conversations/{id}/explain-solution (P1 — solution explainer).

Covers the auth + billing + persistence contract, reusing the chat pipeline:
- happy path (execution_id) streams SSE and persists the assistant message + cost
- inline solution (no execution_id) also works
- 401 without auth, 404 for a cross-org execution (rejection path)
- 402 insufficient credits, 403 monthly-budget exhausted
- 422 when no solution context is supplied

The Anthropic client is mocked at the provider boundary; conversations, messages,
settings, credits, and executions all run against the real PostgreSQL database.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models.llm_conversation import LLMConversation, LLMMessage
from app.models.optimization_model import ExecutionStatus, ModelExecution
from app.services.llm.cost_tracking import reset_budget_cache
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

FORMULATION = {
    "name": "tiny_lp",
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0},
        {"name": "y", "type": "continuous", "lower_bound": 0},
    ],
    "constraints": [{"name": "c1", "expression": "x + y <= 4"}],
    "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
}
RESULT_DATA = {
    "model": {"x": 1.0, "y": 3.0},
    "objective_value": 9.0,
    "solver_status": "optimal",
    "solve_time_seconds": 0.01,
    "variables": [
        {"name": "x", "value": 1.0, "type": "continuous"},
        {"name": "y", "value": 3.0, "type": "continuous"},
    ],
    "sensitivity": {
        "constraints": [{"name": "c1", "shadow_price": 2.0, "is_binding": True}],
        "variables": [{"name": "x", "reduced_cost": 0.0, "is_at_bound": False}],
        "is_approximate": False,
        "note": "Coefficient and RHS ranging are not available for this solver build.",
    },
}


@pytest.fixture(autouse=True)
def _clear_budget_cache():
    """The monthly-budget guardrail caches in-process; reset around each test."""
    reset_budget_cache()
    yield
    reset_budget_cache()


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


def _make_text_stream_events(text="The optimal plan sets x=1, y=3 for objective 9."):
    """Mock Anthropic stream: message_start (usage) + text deltas + message_delta."""
    events = []
    start = MagicMock()
    start.type = "message_start"
    start.message.usage.input_tokens = 500
    events.append(start)
    for i in range(0, len(text), 16):
        ev = MagicMock()
        ev.type = "content_block_delta"
        ev.delta = MagicMock()
        ev.delta.type = "text_delta"
        ev.delta.text = text[i : i + 16]
        events.append(ev)
    final = MagicMock()
    final.type = "message_delta"
    final.delta.stop_reason = "end_turn"
    final.usage.output_tokens = 120
    events.append(final)
    return events


class _MockStreamContext:
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


def _mock_anthropic_client():
    client = MagicMock()
    client.messages.stream = MagicMock(return_value=_MockStreamContext(_make_text_stream_events()))
    return client


def _create_execution(db_session, org_id, result_data=RESULT_DATA) -> ModelExecution:
    exe = ModelExecution(
        id=generate_id("exe_"),
        organization_id=org_id,
        input_data=FORMULATION,
        result_data=result_data,
        status=ExecutionStatus.COMPLETED.value,
        credits_consumed=1,
        solver_status="optimal",
        objective_value=9.0,
    )
    db_session.add(exe)
    db_session.commit()
    return exe


def _url(conv_id: str) -> str:
    return f"/api/v2/llm/conversations/{conv_id}/explain-solution"


class TestExplainSolutionEndpoint:
    def test_happy_path_streams_and_persists_assistant_message(
        self, authenticated_client, db_session, test_conversation, test_organization
    ):
        exe = _create_execution(db_session, test_organization.id)

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=_mock_anthropic_client(),
        ):
            response = authenticated_client.post(
                _url(test_conversation.id), json={"execution_id": exe.id}
            )

        assert response.status_code == 200, response.text
        assert "text/event-stream" in response.headers.get("content-type", "")
        body = response.text
        assert "event: status" in body  # EXPLAINING status forwarded
        assert "event: delta" in body
        assert "event: done" in body
        # Internal token accounting never leaks into the SSE stream.
        assert "event: usage" not in body

        db_session.expire_all()
        assistant = (
            db_session.query(LLMMessage)
            .filter(
                LLMMessage.conversation_id == test_conversation.id,
                LLMMessage.role == "assistant",
            )
            .all()
        )
        assert len(assistant) == 1
        assert assistant[0].input_tokens == 500
        assert assistant[0].output_tokens == 120
        assert assistant[0].cost_eur is not None

    def test_inline_solution_without_execution_id(self, authenticated_client, test_conversation):
        with patch(
            "app.services.llm.formulation_service.get_anthropic_client",
            return_value=_mock_anthropic_client(),
        ):
            response = authenticated_client.post(
                _url(test_conversation.id),
                json={
                    "formulation": FORMULATION,
                    "solution": {"objective_value": 9.0, "solution": {"x": 1.0, "y": 3.0}},
                    "sensitivity": RESULT_DATA["sensitivity"],
                },
            )

        assert response.status_code == 200, response.text
        assert "event: done" in response.text

    def test_requires_auth(self, client, test_conversation):
        response = client.post(_url(test_conversation.id), json={"formulation": FORMULATION})
        assert response.status_code == 401

    def test_cross_org_execution_is_not_found(
        self, authenticated_client, db_session, test_conversation, test_organization_2
    ):
        """An execution owned by another org must not be explainable (no data leak)."""
        foreign_exe = _create_execution(db_session, test_organization_2.id)

        response = authenticated_client.post(
            _url(test_conversation.id), json={"execution_id": foreign_exe.id}
        )
        assert response.status_code == 404

        # Cross-org rejection happens before any credit charge.
        db_session.expire_all()
        db_session.refresh(test_organization_2)
        assistant = (
            db_session.query(LLMMessage)
            .filter(LLMMessage.conversation_id == test_conversation.id)
            .count()
        )
        assert assistant == 0

    def test_insufficient_credits_returns_402(
        self, authenticated_client, db_session, test_conversation, test_organization
    ):
        test_organization.credits_balance = 0
        db_session.commit()

        response = authenticated_client.post(
            _url(test_conversation.id),
            json={"solution": {"objective_value": 9.0, "solution": {"x": 1.0}}},
        )
        assert response.status_code == 402
        assert response.json()["detail"]["error"] == "insufficient_credits"

    def test_budget_exceeded_returns_403(self, authenticated_client, db_session, test_conversation):
        PSS.set(db_session, "LLM_MONTHLY_BUDGET_EUR", "0.05")
        db_session.commit()
        # Push month spend over the 0.05 EUR budget.
        costed = LLMMessage(
            id=generate_id("msg_"),
            conversation_id=test_conversation.id,
            role="assistant",
            content="costed",
            input_tokens=100,
            output_tokens=100,
            cost_eur=0.10,
            created_at=utcnow().replace(tzinfo=None),
        )
        db_session.add(costed)
        db_session.commit()
        reset_budget_cache()

        response = authenticated_client.post(
            _url(test_conversation.id), json={"solution": {"objective_value": 9.0}}
        )
        assert response.status_code == 403
        assert response.json()["detail"]["reason"] == "llm_monthly_budget_exhausted"

    def test_no_solution_context_returns_422(self, authenticated_client, test_conversation):
        response = authenticated_client.post(_url(test_conversation.id), json={})
        assert response.status_code == 422
