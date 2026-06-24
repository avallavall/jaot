"""Tests for LLM conversation endpoints and services.

Covers:
- Formulation generation (LLM-01)
- SSE streaming (LLM-02)
- Validation (LLM-06)
- Conversation persistence (LLM-10)
- Content moderation
- Template integration
"""

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models.llm_conversation import LLMConversation, LLMMessage
from app.schemas.llm import Formulation
from app.services.llm.moderation import moderate_message
from app.services.llm.validation import validate_formulation
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

VALID_FORMULATION = {
    "problem_name": "Shipping Cost Minimizer",
    "summary": "Minimize shipping costs across two routes with capacity constraints.",
    "variables": [
        {
            "name": "units_route_a",
            "type": "integer",
            "lower_bound": 0,
            "upper_bound": 100,
            "description": "Units shipped via route A",
        },
        {
            "name": "units_route_b",
            "type": "integer",
            "lower_bound": 0,
            "upper_bound": 100,
            "description": "Units shipped via route B",
        },
    ],
    "constraints": [
        {
            "name": "demand",
            "expression": "units_route_a + units_route_b >= 50",
            "description": "Must ship at least 50 units total",
        },
    ],
    "objective": {
        "sense": "minimize",
        "expression": "3 * units_route_a + 5 * units_route_b",
        "description": "Minimize total shipping cost",
    },
}

VALID_FORMULATION_JSON = json.dumps(VALID_FORMULATION)


@pytest.fixture
def test_conversation(db_session, test_user, test_organization):
    """Create a test LLM conversation in the DB."""
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


@pytest.fixture
def expired_conversation(db_session, test_user, test_organization):
    """Create an expired LLM conversation in the DB."""
    conv = LLMConversation(
        id=generate_id("conv_"),
        organization_id=test_organization.id,
        user_id=test_user.id,
        created_at=(utcnow() - timedelta(hours=48)).replace(tzinfo=None),
        expires_at=(utcnow() - timedelta(hours=24)).replace(tzinfo=None),
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    return conv


@pytest.fixture
def conversation_with_messages(db_session, test_conversation):
    """Create a conversation with some messages."""
    msg1 = LLMMessage(
        id=generate_id("msg_"),
        conversation_id=test_conversation.id,
        role="user",
        content="Minimize shipping costs for two routes",
        created_at=utcnow().replace(tzinfo=None),
    )
    msg2 = LLMMessage(
        id=generate_id("msg_"),
        conversation_id=test_conversation.id,
        role="assistant",
        content=VALID_FORMULATION_JSON,
        formulation_json=VALID_FORMULATION,
        created_at=(utcnow() + timedelta(seconds=1)).replace(tzinfo=None),
    )
    db_session.add_all([msg1, msg2])
    db_session.commit()
    return test_conversation


def _make_mock_stream_events():
    """Build mock events that simulate an Anthropic streaming response."""
    # Simulate streaming the formulation JSON char by char (we'll do it in chunks)
    text = VALID_FORMULATION_JSON
    chunk_size = 50
    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    events = []
    for chunk in chunks:
        event = MagicMock()
        event.type = "content_block_delta"
        event.delta = MagicMock()
        event.delta.type = "text_delta"
        event.delta.text = chunk
        events.append(event)
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


# Formulation Generation Tests (LLM-01)


class TestFormulationSchema:
    """Test the Formulation Pydantic schema."""

    def test_formulation_roundtrip(self):
        """A valid formulation dict roundtrips through Pydantic."""
        f = Formulation.model_validate(VALID_FORMULATION)
        data = f.model_dump()
        assert data["problem_name"] == "Shipping Cost Minimizer"
        assert len(data["variables"]) == 2
        assert len(data["constraints"]) == 1


class TestFormulationGeneration:
    """Test the formulation generation service."""

    @pytest.mark.asyncio
    async def test_formulation_generation_yields_events(self):
        """Mock Anthropic, call generate_formulation(), collect events."""
        mock_events = _make_mock_stream_events()
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=MockStreamContext(mock_events))

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client", return_value=mock_client
        ):
            from app.services.llm.formulation_service import generate_formulation

            events = []
            async for event in generate_formulation(
                [{"role": "user", "content": "Minimize shipping costs"}],
                "claude-sonnet-4-6",
            ):
                events.append(event)

        # Should have delta events, formulation event, done event
        event_types = [e["type"] for e in events]
        assert "delta" in event_types
        assert "formulation" in event_types
        assert "done" in event_types

        # Formulation event should have valid data
        formulation_event = next(e for e in events if e["type"] == "formulation")
        assert formulation_event["data"]["problem_name"] == "Shipping Cost Minimizer"

    @pytest.mark.asyncio
    async def test_formulation_generation_filters_thinking(self):
        """Thinking delta events should not be yielded."""
        thinking_event = MagicMock()
        thinking_event.type = "content_block_delta"
        thinking_event.delta = MagicMock()
        thinking_event.delta.type = "thinking_delta"
        thinking_event.delta.text = "Let me think..."

        text_events = _make_mock_stream_events()
        all_events = [thinking_event] + text_events

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=MockStreamContext(all_events))

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client", return_value=mock_client
        ):
            from app.services.llm.formulation_service import generate_formulation

            events = []
            async for event in generate_formulation(
                [{"role": "user", "content": "test"}],
                "claude-opus-4-6",
                thinking=True,
            ):
                events.append(event)

        # No thinking text should appear in delta events
        delta_texts = [e.get("text", "") for e in events if e["type"] == "delta"]
        assert "Let me think..." not in delta_texts


# SSE Streaming Tests (LLM-02)


class TestSSEStreaming:
    """Test the SSE streaming endpoint."""

    def test_sse_endpoint_returns_event_stream(self, authenticated_client, test_conversation):
        """POST /conversations/{id}/messages returns text/event-stream with at least one event."""
        mock_events = _make_mock_stream_events()
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=MockStreamContext(mock_events))

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client", return_value=mock_client
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={"message": "Minimize shipping costs for two routes"},
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        # Body must contain at least one SSE event line
        body = response.text
        assert any(line.startswith("event:") for line in body.split("\n")), (
            "SSE response body did not contain any 'event:' lines"
        )

    def test_sse_events_contain_delta_and_formulation(
        self, authenticated_client, test_conversation
    ):
        """Parse SSE event stream, verify delta, formulation, done events."""
        mock_events = _make_mock_stream_events()
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=MockStreamContext(mock_events))

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client", return_value=mock_client
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={"message": "Minimize shipping costs for two routes"},
            )

        # Parse SSE events from response body
        body = response.text
        events_found = set()
        for line in body.split("\n"):
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
                events_found.add(event_name)

        assert "delta" in events_found
        assert "formulation" in events_found
        assert "done" in events_found

    def test_sse_endpoint_requires_auth(self, client, test_conversation):
        """Verify 401 without auth token."""
        response = client.post(
            f"/api/v2/llm/conversations/{test_conversation.id}/messages",
            json={"message": "test"},
        )
        # Without auth, should get 401 (via middleware or dependency)
        assert response.status_code == 401


# Validation Tests (LLM-06)


class TestFormulationValidation:
    """Test formulation validation logic."""

    def test_validate_formulation_catches_undeclared_variable(self):
        """Constraint references variable not in variables list."""
        formulation = {
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
                {"name": "c1", "expression": "x + unknown_var <= 10", "description": "test"},
            ],
            "objective": {"sense": "minimize", "expression": "x", "description": "test"},
        }
        errors = validate_formulation(formulation)
        assert any("undeclared variable 'unknown_var'" in e["message"] for e in errors)

    def test_validate_formulation_catches_bound_error(self):
        """lower_bound > upper_bound should produce an error."""
        formulation = {
            "variables": [
                {
                    "name": "x",
                    "type": "continuous",
                    "lower_bound": 10,
                    "upper_bound": 5,
                    "description": "var x",
                },
            ],
            "constraints": [],
            "objective": {"sense": "minimize", "expression": "x", "description": "test"},
        }
        errors = validate_formulation(formulation)
        assert any("invalid bounds" in e["message"].lower() for e in errors)

    def test_validate_formulation_passes_valid(self):
        """Well-formed formulation should have no errors (except optional warnings)."""
        errors = validate_formulation(VALID_FORMULATION)
        # Only non-error warnings (like empty constraints) are acceptable
        actual_errors = [e for e in errors if "No constraints" not in e["message"]]
        assert len(actual_errors) == 0

    def test_validate_formulation_empty_variables(self):
        """Empty variables list should produce an error."""
        formulation = {
            "variables": [],
            "constraints": [],
            "objective": {"sense": "minimize", "expression": "0", "description": "test"},
        }
        errors = validate_formulation(formulation)
        assert any("No variables defined" in e["message"] for e in errors)

    def test_sse_stream_includes_validation_errors(self, authenticated_client, test_conversation):
        """Stream with invalid formulation includes validation_errors event."""
        invalid_formulation = {
            "problem_name": "Test",
            "summary": "Test",
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
                {
                    "name": "c1",
                    "expression": "x + UNDECLARED_VAR <= 10",
                    "description": "bad constraint",
                },
            ],
            "objective": {"sense": "minimize", "expression": "x", "description": "test"},
        }
        invalid_json = json.dumps(invalid_formulation)

        # Create mock events that stream the invalid formulation
        chunk_size = 50
        chunks = [invalid_json[i : i + chunk_size] for i in range(0, len(invalid_json), chunk_size)]
        mock_events = []
        for chunk in chunks:
            event = MagicMock()
            event.type = "content_block_delta"
            event.delta = MagicMock()
            event.delta.type = "text_delta"
            event.delta.text = chunk
            mock_events.append(event)

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=MockStreamContext(mock_events))

        with patch(
            "app.services.llm.formulation_service.get_anthropic_client", return_value=mock_client
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={"message": "Minimize cost"},
            )

        body = response.text
        events_found = set()
        for line in body.split("\n"):
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
                events_found.add(event_name)

        assert "validation_errors" in events_found


# Conversation Persistence Tests (LLM-10)


class TestConversationCRUD:
    """Test conversation CRUD operations."""

    def test_create_conversation(self, authenticated_client):
        """POST /conversations returns 201 with conv_ prefixed ID and expires_at."""
        response = authenticated_client.post(
            "/api/v2/llm/conversations",
            json={},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"].startswith("conv_")
        assert "expires_at" in data
        assert "created_at" in data

    def test_get_conversation_with_messages(self, authenticated_client, conversation_with_messages):
        """GET /conversations/{id} returns messages in order."""
        response = authenticated_client.get(
            f"/api/v2/llm/conversations/{conversation_with_messages.id}",
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"

    def test_expired_conversation_returns_404(self, authenticated_client, expired_conversation):
        """GET on expired conversation returns 404."""
        response = authenticated_client.get(
            f"/api/v2/llm/conversations/{expired_conversation.id}",
        )
        assert response.status_code == 404

    def test_delete_conversation_cascades(
        self, authenticated_client, db_session, conversation_with_messages
    ):
        """Delete conversation, verify messages also deleted."""
        conv_id = conversation_with_messages.id

        response = authenticated_client.delete(
            f"/api/v2/llm/conversations/{conv_id}",
        )
        assert response.status_code == 204

        # Verify conversation is gone
        assert db_session.query(LLMConversation).filter_by(id=conv_id).first() is None
        # Verify messages are gone (CASCADE)
        assert db_session.query(LLMMessage).filter_by(conversation_id=conv_id).count() == 0

    def test_list_conversations_excludes_expired(
        self, authenticated_client, test_conversation, expired_conversation
    ):
        """List only returns non-expired conversations."""
        response = authenticated_client.get("/api/v2/llm/conversations")
        assert response.status_code == 200
        data = response.json()
        ids = [c["id"] for c in data["items"]]
        assert test_conversation.id in ids
        assert expired_conversation.id not in ids

    def test_create_conversation_with_model_id(self, authenticated_client):
        """POST /conversations with model_id stores and returns it."""
        response = authenticated_client.post(
            "/api/v2/llm/conversations",
            json={"model_id": "doc_abc123"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["model_id"] == "doc_abc123"

    def test_list_conversations_filters_by_model_id(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        """GET /conversations?model_id=X returns only matching conversations."""
        from datetime import timedelta

        # Create two conversations with different model_ids
        conv1 = LLMConversation(
            id=generate_id("conv_"),
            organization_id=test_organization.id,
            user_id=test_user.id,
            model_id="doc_aaa",
            created_at=utcnow().replace(tzinfo=None),
            expires_at=(utcnow() + timedelta(hours=24)).replace(tzinfo=None),
        )
        conv2 = LLMConversation(
            id=generate_id("conv_"),
            organization_id=test_organization.id,
            user_id=test_user.id,
            model_id="doc_bbb",
            created_at=utcnow().replace(tzinfo=None),
            expires_at=(utcnow() + timedelta(hours=24)).replace(tzinfo=None),
        )
        db_session.add_all([conv1, conv2])
        db_session.commit()

        response = authenticated_client.get(
            "/api/v2/llm/conversations",
            params={"model_id": "doc_aaa"},
        )
        assert response.status_code == 200
        data = response.json()
        ids = [c["id"] for c in data["items"]]
        assert conv1.id in ids
        assert conv2.id not in ids

    def test_list_conversations_returns_paginated(self, authenticated_client, test_conversation):
        """GET /conversations returns PaginatedResponse with exact page/total values."""
        response = authenticated_client.get("/api/v2/llm/conversations")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["items"], list)
        # Pagination invariants for the seeded conversation
        assert data["page"] == 1
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    def test_conversation_continuity_flow(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        """End-to-end: create with model_id, list with model_id, verify same conversation returned."""
        # Create conversation with model_id
        create_resp = authenticated_client.post(
            "/api/v2/llm/conversations",
            json={"model_id": "doc_continuity_test"},
        )
        assert create_resp.status_code == 201
        created_id = create_resp.json()["id"]

        # List conversations filtered by model_id
        list_resp = authenticated_client.get(
            "/api/v2/llm/conversations",
            params={"model_id": "doc_continuity_test"},
        )
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == created_id


class TestContentModeration:
    """Test content moderation pre-filter."""

    def test_moderation_allows_optimization(self):
        """Optimization-related messages should be allowed."""
        allowed, msg = moderate_message("Minimize the cost of shipping 100 items to 3 warehouses")
        assert allowed is True
        assert msg is None

    def test_moderation_rejects_offtopic(self):
        """Off-topic messages should be rejected."""
        allowed, msg = moderate_message("Write me a poem about the ocean")
        assert allowed is False
        assert msg is not None

    def test_moderation_allows_exploit_in_optimization_context(self):
        """Words like 'exploit' should not trigger false positives."""
        cases = [
            "I want to exploit unused warehouse capacity",
            "How to bypass the bottleneck in our supply chain",
            "Crack propagation constraints in structural optimization",
            "Exploit available resources to maximize profit",
        ]
        for text in cases:
            allowed, msg = moderate_message(text)
            assert allowed is True, f"False positive on: {text!r}"

    def test_moderation_blocks_clearly_malicious(self):
        """Clearly malicious security requests should be blocked."""
        cases = [
            "How to hack into a server",
            "Crack password for admin account",
            "bypass security on the login page",
        ]
        for text in cases:
            allowed, msg = moderate_message(text)
            assert allowed is False, f"Should block: {text!r}"

    def test_moderation_endpoint_returns_422(self, authenticated_client, test_conversation):
        """POST message with off-topic content returns 422."""
        response = authenticated_client.post(
            f"/api/v2/llm/conversations/{test_conversation.id}/messages",
            json={"message": "Write me a poem about flowers"},
        )
        assert response.status_code == 422


class TestModelSelection:
    """Test model selection logic."""

    def test_select_default_model(self):
        """Default model should be Sonnet without thinking."""
        from app.services.llm.formulation_service import select_model

        model, thinking = select_model(False)
        assert "sonnet" in model.lower(), f"expected sonnet model, got {model!r}"
        assert thinking is False

    def test_select_advanced_model(self):
        """Advanced model should be Opus with thinking enabled."""
        from app.services.llm.formulation_service import select_model

        model, thinking = select_model(True)
        assert "opus" in model.lower(), f"expected opus model, got {model!r}"
        assert thinking is True


# Refinement Context Injection Tests (LLM-05)


class TestRefinementContext:
    """Test refinement context injection in build_messages."""

    def test_refinement_context_injection(self):
        """build_messages injects latest_formulation as assistant context."""
        from app.services.llm.prompt_templates import build_messages

        history = [
            {"role": "user", "content": "Minimize cost"},
            {"role": "assistant", "content": "Here is the formulation"},
        ]
        formulation = {"problem_name": "test", "variables": []}

        msgs = build_messages(history, "Add a constraint", latest_formulation=formulation)

        # History (2) + injected assistant (1) + new user (1) = 4
        assert len(msgs) == 4
        # The injected assistant message should contain the formulation
        assert msgs[2]["role"] == "assistant"
        assert "Current formulation:" in msgs[2]["content"]
        assert '"problem_name": "test"' in msgs[2]["content"]
        # New user message is last
        assert msgs[3]["role"] == "user"
        assert msgs[3]["content"] == "Add a constraint"

    def test_no_formulation_context_when_none(self):
        """build_messages does NOT inject context when latest_formulation is None."""
        from app.services.llm.prompt_templates import build_messages

        history = [{"role": "user", "content": "Hello"}]
        msgs = build_messages(history, "New message", latest_formulation=None)

        # History (1) + new user (1) = 2
        assert len(msgs) == 2

    def test_history_truncation(self):
        """build_messages truncates history to max_history messages."""
        from app.services.llm.prompt_templates import build_messages

        # Create 20 history messages
        history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]

        msgs = build_messages(history, "new", max_history=5)

        # Truncated history (5) + new user (1) = 6
        assert len(msgs) == 6
        # First message should be from the tail of history
        assert msgs[0]["content"] == "msg 15"

    def test_history_truncation_with_formulation(self):
        """Truncation + formulation injection works correctly together."""
        from app.services.llm.prompt_templates import build_messages

        history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        formulation = {"problem_name": "test"}

        msgs = build_messages(history, "refine", max_history=3, latest_formulation=formulation)

        # Truncated history (3) + injected assistant (1) + new user (1) = 5
        assert len(msgs) == 5
        assert msgs[3]["role"] == "assistant"
        assert msgs[4]["content"] == "refine"


# Rate Limiting Tests (LLM-08)


class TestLLMRateLimiting:
    """Test LLM rate limiting in send_message endpoint."""

    def test_llm_rate_limiting_returns_429(self, authenticated_client, test_conversation):
        """Rate-limited requests return 429 with Retry-After header and retry_after in payload."""
        with patch(
            "app.api.v2.llm.check_rate_limit",
            return_value=(
                False,
                {
                    "error": "rate_limit_exceeded",
                    "message": "Rate limit exceeded",
                    "retry_after": 30,
                },
            ),
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={"message": "Minimize cost of shipping"},
            )

        assert response.status_code == 429
        # HTTP Retry-After header surfaces the wait window
        assert response.headers.get("retry-after") == "30"
        # JSON detail payload echoes the retry_after value
        detail = response.json()["detail"]
        assert detail["retry_after"] == 30
        assert detail["error"] == "rate_limit_exceeded"

    def test_llm_insufficient_credits_returns_402(
        self, authenticated_client, test_conversation, test_organization, db_session
    ):
        """Insufficient credits returns 402."""
        # Set credits to 0 and commit so the endpoint session sees it
        test_organization.credits_balance = 0
        db_session.commit()

        with patch(
            "app.api.v2.llm.check_rate_limit",
            return_value=(True, {"minute_remaining": 9}),
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={"message": "Minimize cost of shipping"},
            )

        assert response.status_code == 402
        detail = response.json()["detail"]
        assert detail["error"] == "insufficient_credits"


# Explanation Mode Tests (LLM-09)


class TestExplanationMode:
    """Test explanation response type routing."""

    def test_explanation_response_type_schema(self):
        """ChatMessageRequest accepts response_type='explanation'."""
        from app.schemas.llm import ChatMessageRequest

        req = ChatMessageRequest(message="Why did my solve fail?", response_type="explanation")
        assert req.response_type == "explanation"

    def test_explanation_response_type_default(self):
        """ChatMessageRequest defaults to 'formulation'."""
        from app.schemas.llm import ChatMessageRequest

        req = ChatMessageRequest(message="test")
        assert req.response_type == "formulation"

    def test_explanation_response_type_invalid(self):
        """Invalid response_type is rejected."""
        from pydantic import ValidationError

        from app.schemas.llm import ChatMessageRequest

        with pytest.raises(ValidationError):
            ChatMessageRequest(message="test", response_type="invalid")

    def test_explanation_endpoint_uses_text_generator(
        self, authenticated_client, test_conversation, test_organization, db_session
    ):
        """Explanation response_type routes to generate_text_response."""
        test_organization.credits_balance = 100
        db_session.commit()

        async def mock_text_gen(messages, model, thinking, **kwargs):
            yield {"type": "delta", "text": "The infeasible status means..."}
            yield {"type": "done"}

        with (
            patch(
                "app.api.v2.llm.check_rate_limit",
                return_value=(True, {"minute_remaining": 9}),
            ),
            patch(
                "app.api.v2.llm.generate_text_response",
                side_effect=mock_text_gen,
            ),
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={
                    "message": "Why did my solve fail?",
                    "response_type": "explanation",
                },
            )

        assert response.status_code == 200
        body = response.text
        # Should have delta and done events
        events_found = set()
        for line in body.split("\n"):
            if line.startswith("event:"):
                events_found.add(line.split(":", 1)[1].strip())
        assert "delta" in events_found
        assert "done" in events_found


class TestCreditDeduction:
    """Test credit deduction after successful LLM stream."""

    def test_credit_deduction_on_success(
        self, authenticated_client, test_conversation, test_organization, db_session
    ):
        """Credits are deducted after successful stream completion."""
        test_organization.credits_balance = 50
        db_session.commit()

        mock_events = _make_mock_stream_events()
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=MockStreamContext(mock_events))

        with (
            patch(
                "app.api.v2.llm.check_rate_limit",
                return_value=(True, {"minute_remaining": 9}),
            ),
            patch(
                "app.services.llm.formulation_service.get_anthropic_client",
                return_value=mock_client,
            ),
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={"message": "Minimize shipping costs for two routes"},
            )

        assert response.status_code == 200
        # Refresh org from DB to check credit deduction
        db_session.refresh(test_organization)
        # LLM_CREDIT_COST_PER_MESSAGE default is 2
        assert test_organization.credits_balance == 48

    def test_credit_refund_on_stream_failure(
        self, authenticated_client, test_conversation, test_organization, db_session
    ):
        """Credits are refunded when the LLM stream raises mid-flight.

        Money path: pre-pay → stream raises → must refund (or never deduct).
        Without this guard, a SIGTERM after deduct but before stream end
        would leave the user charged but with no result.
        """
        from app.models.credit_transaction import CreditTransaction

        test_organization.credits_balance = 50
        db_session.commit()
        starting_balance = test_organization.credits_balance

        class _RaisingStream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def __aiter__(self):
                return self._iter()

            async def _iter(self):
                # Yield one delta then raise to simulate mid-flight failure
                event = MagicMock()
                event.type = "content_block_delta"
                event.delta = MagicMock()
                event.delta.type = "text_delta"
                event.delta.text = "{"
                yield event
                raise RuntimeError("Anthropic stream crashed")

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=_RaisingStream())

        with (
            patch(
                "app.api.v2.llm.check_rate_limit",
                return_value=(True, {"minute_remaining": 9}),
            ),
            patch(
                "app.services.llm.formulation_service.get_anthropic_client",
                return_value=mock_client,
            ),
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={"message": "Minimize shipping costs for two routes"},
            )

        # Stream endpoint returns 200 but emits an error event in the body
        assert response.status_code == 200

        # Refresh and verify net balance unchanged (pre-pay was refunded)
        db_session.expire_all()
        org_after = (
            db_session.query(test_organization.__class__).filter_by(id=test_organization.id).first()
        )
        assert org_after.credits_balance == starting_balance, (
            f"credits not refunded: {starting_balance} -> {org_after.credits_balance}"
        )

        # And the refund transaction was recorded
        refund_count = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == test_organization.id,
                CreditTransaction.reference_type == "llm_message_refund",
            )
            .count()
        )
        assert refund_count == 1

    def test_no_orphaned_assistant_message_on_stream_failure(
        self, authenticated_client, test_conversation, test_organization, db_session
    ):
        """When the stream fails mid-flight, no LLMMessage row should be persisted.

        The audit's missing-test #3: orphaned LLMMessage rows must not appear
        if the SSE stream errors out before reaching the 'done' event.
        """
        test_organization.credits_balance = 50
        db_session.commit()

        # Count assistant messages before the request
        assistant_msgs_before = (
            db_session.query(LLMMessage)
            .filter_by(conversation_id=test_conversation.id, role="assistant")
            .count()
        )

        class _RaisingStream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def __aiter__(self):
                return self._iter()

            async def _iter(self):
                event = MagicMock()
                event.type = "content_block_delta"
                event.delta = MagicMock()
                event.delta.type = "text_delta"
                event.delta.text = "{"
                yield event
                raise RuntimeError("Anthropic stream crashed mid-flight")

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=_RaisingStream())

        with (
            patch(
                "app.api.v2.llm.check_rate_limit",
                return_value=(True, {"minute_remaining": 9}),
            ),
            patch(
                "app.services.llm.formulation_service.get_anthropic_client",
                return_value=mock_client,
            ),
        ):
            response = authenticated_client.post(
                f"/api/v2/llm/conversations/{test_conversation.id}/messages",
                json={"message": "Minimize shipping costs for two routes"},
            )

        assert response.status_code == 200
        # Verify NO new assistant message row was persisted
        db_session.expire_all()
        assistant_msgs_after = (
            db_session.query(LLMMessage)
            .filter_by(conversation_id=test_conversation.id, role="assistant")
            .count()
        )
        assert assistant_msgs_after == assistant_msgs_before, (
            f"orphaned assistant message persisted: "
            f"{assistant_msgs_before} -> {assistant_msgs_after}"
        )


class TestFailureExplanationPrompt:
    """Test the FAILURE_EXPLANATION_PROMPT template."""

    def test_failure_explanation_prompt_format(self):
        """FAILURE_EXPLANATION_PROMPT formats correctly with status and formulation.

        Asserts the formatted result contains the status and JSON in their
        EXPECTED placeholder positions, not just as stray substrings.
        """
        from app.services.llm.prompt_templates import FAILURE_EXPLANATION_PROMPT

        formulation_json = '{"problem_name": "shipping_optimization"}'
        result = FAILURE_EXPLANATION_PROMPT.format(
            status="infeasible",
            formulation_json=formulation_json,
        )
        # Non-empty result that no longer contains unfilled placeholders
        assert isinstance(result, str) and len(result) > 0
        assert "{status}" not in result
        assert "{formulation_json}" not in result

        # Status appears in BOTH places where the template puts it (top sentence
        # and the explicit "Status:" line below the formulation block)
        assert "got a infeasible result" in result
        assert "Status: infeasible" in result

        # Formulation JSON appears immediately after the "Formulation:" header
        assert f"Formulation:\n{formulation_json}" in result
