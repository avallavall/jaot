"""Tests for the ModelProject explainers (P1c):
- POST /llm/conversations/{id}/explain-model — explain an (unsolved) model
- POST /llm/conversations/{id}/explain-diff — narrate the change between two versions

Covers the auth + billing + grounding contract, reusing the chat pipeline:
- happy path (project draft / two versions) streams SSE + persists the assistant turn
- inline formulation also works
- 401 without auth, 404 for a cross-org project (rejection path)
- 403 monthly-budget exhausted, 422 when no model is supplied
- CONTRACT-TEST: the diff narration prompt is built from the Python-computed diff

The Anthropic client is mocked at the provider boundary; conversations, messages,
projects, versions, settings and credits all run against the real PostgreSQL database.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models.llm_conversation import LLMConversation, LLMMessage
from app.services import model_project_service as projects_svc
from app.services.llm.cost_tracking import reset_budget_cache
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

MODEL_A = {
    "name": "tiny_lp",
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0},
        {"name": "y", "type": "continuous", "lower_bound": 0},
    ],
    "constraints": [{"name": "c1", "expression": "x + y <= 4"}],
    "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
}
# MODEL_B tightens the model with an extra constraint — the diff must show it added.
MODEL_B = {
    "name": "tiny_lp",
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0},
        {"name": "y", "type": "continuous", "lower_bound": 0},
    ],
    "constraints": [
        {"name": "c1", "expression": "x + y <= 4"},
        {"name": "c2", "expression": "x <= 2"},
    ],
    "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
}


@pytest.fixture(autouse=True)
def _clear_budget_cache():
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


@pytest.fixture
def project_with_two_versions(db_session, test_user, test_organization):
    """A ModelProject seeded at MODEL_A (v1), then committed at MODEL_B (v2)."""
    project = projects_svc.create_seeded(
        db_session,
        org_id=test_organization.id,
        user_id=test_user.id,
        name="Tiny LP",
        problem_json=MODEL_A,
        source_type="blank",
        auto_commit_summary="initial model",
    )
    projects_svc.update_draft(db_session, project, model_json=MODEL_B, expected_lock=None)
    projects_svc.commit_version(db_session, project, user_id=test_user.id, summary="cap x at 2")
    db_session.commit()
    versions = projects_svc.list_versions(db_session, project.id, test_organization.id)
    # Newest first → [v2 (cap x at 2), v1 (initial)].
    return project, versions[1].id, versions[0].id


def _make_text_stream_events(text="This model maximizes 3x+2y subject to a budget."):
    events = []
    start = MagicMock()
    start.type = "message_start"
    start.message.usage.input_tokens = 400
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
    final.usage.output_tokens = 90
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


def _patched_client():
    return patch(
        "app.services.llm.formulation_service.get_anthropic_client",
        return_value=_mock_anthropic_client(),
    )


def _explain_model_url(conv_id: str) -> str:
    return f"/api/v2/llm/conversations/{conv_id}/explain-model"


def _explain_diff_url(conv_id: str) -> str:
    return f"/api/v2/llm/conversations/{conv_id}/explain-diff"


class TestExplainModelEndpoint:
    def test_happy_path_draft_streams_and_persists(
        self, authenticated_client, db_session, test_conversation, project_with_two_versions
    ):
        project, _v1, _v2 = project_with_two_versions
        with _patched_client():
            response = authenticated_client.post(
                _explain_model_url(test_conversation.id), json={"project_id": project.id}
            )

        assert response.status_code == 200, response.text
        assert "text/event-stream" in response.headers.get("content-type", "")
        body = response.text
        assert "event: status" in body  # EXPLAINING forwarded
        assert "event: delta" in body
        assert "event: done" in body
        assert "event: usage" not in body  # internal accounting never leaks

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
        assert assistant[0].cost_eur is not None

    def test_explain_committed_version(
        self, authenticated_client, test_conversation, project_with_two_versions
    ):
        project, v1, _v2 = project_with_two_versions
        with _patched_client():
            response = authenticated_client.post(
                _explain_model_url(test_conversation.id),
                json={"project_id": project.id, "version_id": v1},
            )
        assert response.status_code == 200, response.text
        assert "event: done" in response.text

    def test_inline_formulation(self, authenticated_client, test_conversation):
        with _patched_client():
            response = authenticated_client.post(
                _explain_model_url(test_conversation.id), json={"formulation": MODEL_A}
            )
        assert response.status_code == 200, response.text
        assert "event: done" in response.text

    def test_requires_auth(self, client, test_conversation):
        response = client.post(
            _explain_model_url(test_conversation.id), json={"formulation": MODEL_A}
        )
        assert response.status_code == 401

    def test_cross_org_project_is_not_found(
        self, authenticated_client, db_session, test_conversation, test_user, test_organization_2
    ):
        """A project owned by another org must not be explainable (no data leak)."""
        foreign = projects_svc.create_seeded(
            db_session,
            org_id=test_organization_2.id,
            user_id=test_user.id,
            name="Foreign",
            problem_json=MODEL_A,
            source_type="blank",
            auto_commit_summary="x",
        )
        db_session.commit()

        response = authenticated_client.post(
            _explain_model_url(test_conversation.id), json={"project_id": foreign.id}
        )
        assert response.status_code == 404

        # Cross-org rejection happens before any credit charge / turn persistence.
        db_session.expire_all()
        count = (
            db_session.query(LLMMessage)
            .filter(LLMMessage.conversation_id == test_conversation.id)
            .count()
        )
        assert count == 0

    def test_budget_exceeded_returns_403(self, authenticated_client, db_session, test_conversation):
        PSS.set(db_session, "LLM_MONTHLY_BUDGET_EUR", "0.05")
        db_session.commit()
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
            _explain_model_url(test_conversation.id), json={"formulation": MODEL_A}
        )
        assert response.status_code == 403
        assert response.json()["detail"]["reason"] == "llm_monthly_budget_exhausted"

    def test_no_model_context_returns_422(self, authenticated_client, test_conversation):
        response = authenticated_client.post(_explain_model_url(test_conversation.id), json={})
        assert response.status_code == 422


class TestExplainDiffEndpoint:
    def test_happy_path_streams_computed_diff(
        self, authenticated_client, db_session, test_conversation, project_with_two_versions
    ):
        project, v1, v2 = project_with_two_versions
        with _patched_client():
            response = authenticated_client.post(
                _explain_diff_url(test_conversation.id),
                json={"project_id": project.id, "from_version_id": v1, "to_version_id": v2},
            )
        assert response.status_code == 200, response.text
        assert "event: delta" in response.text
        assert "event: done" in response.text

        db_session.expire_all()
        assistant = (
            db_session.query(LLMMessage)
            .filter(
                LLMMessage.conversation_id == test_conversation.id,
                LLMMessage.role == "assistant",
            )
            .count()
        )
        assert assistant == 1

    def test_cross_org_project_is_not_found(
        self,
        authenticated_client,
        db_session,
        test_conversation,
        test_user,
        test_organization_2,
    ):
        foreign = projects_svc.create_seeded(
            db_session,
            org_id=test_organization_2.id,
            user_id=test_user.id,
            name="Foreign",
            problem_json=MODEL_A,
            source_type="blank",
            auto_commit_summary="x",
        )
        projects_svc.update_draft(db_session, foreign, model_json=MODEL_B, expected_lock=None)
        projects_svc.commit_version(db_session, foreign, user_id=test_user.id, summary="v2")
        db_session.commit()
        versions = projects_svc.list_versions(db_session, foreign.id, test_organization_2.id)

        response = authenticated_client.post(
            _explain_diff_url(test_conversation.id),
            json={
                "project_id": foreign.id,
                "from_version_id": versions[1].id,
                "to_version_id": versions[0].id,
            },
        )
        assert response.status_code == 404

    def test_unknown_version_returns_404(
        self, authenticated_client, test_conversation, project_with_two_versions
    ):
        project, v1, _v2 = project_with_two_versions
        response = authenticated_client.post(
            _explain_diff_url(test_conversation.id),
            json={
                "project_id": project.id,
                "from_version_id": v1,
                "to_version_id": "mpv_does_not_exist",
            },
        )
        assert response.status_code == 404


def test_diff_prompt_is_grounded_in_the_computed_diff(db_session, test_user, test_organization):
    """CONTRACT-TEST: the diff narration prompt is constructed from the Python-computed
    ``diff_versions`` output (added/removed/modified) — never free text. This is the
    grounding guarantee that makes 'explain the change' hallucination-proof."""
    from app.services.llm.prompt_templates import build_version_diff_prompt

    project = projects_svc.create_seeded(
        db_session,
        org_id=test_organization.id,
        user_id=test_user.id,
        name="P",
        problem_json=MODEL_A,
        source_type="blank",
        auto_commit_summary="v1",
    )
    projects_svc.update_draft(db_session, project, model_json=MODEL_B, expected_lock=None)
    projects_svc.commit_version(db_session, project, user_id=test_user.id, summary="v2")
    db_session.commit()
    versions = projects_svc.list_versions(db_session, project.id, test_organization.id)
    v_from, v_to = versions[1], versions[0]

    diff = projects_svc.diff_versions(v_from, v_to)
    # The computed diff must capture the added constraint c2.
    assert any(e.change == "added" and e.name == "c2" for e in diff.entries)

    prompt = build_version_diff_prompt(
        v_from.model_json, v_to.model_json, diff.model_dump(mode="json"), "v1", "v2"
    )
    # The prompt embeds the computed diff verbatim (c2/added), not a free-text summary.
    assert "c2" in prompt
    assert "added" in prompt
    assert "Structural diff" in prompt


def test_model_explanation_prompt_embeds_small_formulation_in_full():
    """A normal-size formulation is embedded verbatim (no sampling), so nothing is lost."""
    from app.services.llm.prompt_templates import build_model_explanation_prompt

    stats = {"num_variables": 2, "num_constraints": 1, "problem_class": "LP"}
    prompt = build_model_explanation_prompt(MODEL_A, stats)

    # Full formulation present; the SAMPLED flag must NOT appear for a tiny model.
    assert "## Formulation\n" in prompt
    assert "SAMPLED" not in prompt
    assert '"tiny_lp"' in prompt
    assert "3*x + 2*y" in prompt  # objective expression embedded verbatim


def test_model_explanation_prompt_bounds_a_huge_formulation():
    """CONTRACT-TEST: a huge model is SAMPLED so the prompt never blows the context window.

    Regression for the 2026-06-30 'prompt is too long: 3.85M tokens' 400 from Anthropic
    on scenario_16 (48k variables). The full dump must never reach the provider; the
    statistics block stays authoritative for the complete counts.
    """
    from app.services.llm.prompt_templates import (
        MODEL_EXPLANATION_FORMULATION_MAX_TOKENS,
        build_model_explanation_prompt,
    )
    from app.services.llm.token_estimation import estimate_tokens

    n_vars = 48_556
    huge = {
        "name": "scenario_16",
        "variables": [
            {"name": f"assign_e{i}", "type": "binary", "lower_bound": 0, "upper_bound": 1}
            for i in range(n_vars)
        ],
        "constraints": [
            {"name": f"cover_{j}", "expression": " + ".join(f"assign_e{k}" for k in range(200))}
            for j in range(685)
        ],
        "objective": {
            "sense": "minimize",
            "expression": " + ".join(f"c{i}*assign_e{i}" for i in range(n_vars)),
        },
    }
    stats = {"num_variables": n_vars, "num_constraints": 685, "problem_class": "BIP"}

    prompt = build_model_explanation_prompt(huge, stats)

    # The whole prompt must fit comfortably under the provider context window.
    assert estimate_tokens(prompt) <= MODEL_EXPLANATION_FORMULATION_MAX_TOKENS + 4000
    # It is flagged as sampled and points the model at the authoritative statistics.
    assert "SAMPLED" in prompt
    assert "omitted for size" in prompt
    # Authoritative counts still reach the model via the statistics block.
    assert "48556" in prompt or "48,556" in prompt
    # Long expressions are clipped, not dumped whole.
    assert "[+" in prompt and "chars]" in prompt
