"""BYOK billing behavior in the LLM endpoints.

Proves the money-saving contract: when an org has its own Anthropic key, an LLM call
(a) bypasses the platform monthly-budget guardrail, (b) charges no JAOT credits, and
(c) records no platform ``cost_eur``. The contrast (no key + budget exhausted → 403)
confirms the guardrail still applies to platform-key orgs.

The org's real encrypted key is set; only the low-level client factory is mocked, so
the actual BYOK resolution path runs end-to-end.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from app.models.llm_conversation import LLMConversation, LLMMessage
from app.models.optimization_model import ExecutionStatus, ModelExecution
from app.services.llm import byok
from app.services.llm.cost_tracking import reset_budget_cache
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

FORMULATION = {
    "name": "infeasible_lp",
    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
    "constraints": [
        {"name": "floor", "expression": "x >= 10"},
        {"name": "ceiling", "expression": "x <= 5"},
    ],
    "objective": {"sense": "maximize", "expression": "x"},
}
RESULT_DATA = {
    "solver_status": "infeasible",
    "model": None,
    "infeasibility_analysis": {
        "iis_constraints": ["floor", "ceiling"],
        "iis_variable_bounds": [],
        "conflict_type": "constraint",
        "method": "iis",
        "note": None,
    },
}


def _make_text_stream_events(text="Constraints floor and ceiling conflict."):
    events = []
    start = MagicMock()
    start.type = "message_start"
    start.message.usage.input_tokens = 300
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
    final.usage.output_tokens = 60
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


def _mock_byok_client():
    client = MagicMock()
    client.messages.stream = MagicMock(return_value=_MockStreamContext(_make_text_stream_events()))
    return client


def _conversation(db_session, org_id, user_id):
    conv = LLMConversation(
        id=generate_id("conv_"),
        organization_id=org_id,
        user_id=user_id,
        created_at=utcnow().replace(tzinfo=None),
        expires_at=(utcnow() + timedelta(hours=24)).replace(tzinfo=None),
    )
    db_session.add(conv)
    db_session.commit()
    return conv


def _infeasible_execution(db_session, org_id):
    exe = ModelExecution(
        id=generate_id("exe_"),
        organization_id=org_id,
        input_data=FORMULATION,
        result_data=RESULT_DATA,
        status=ExecutionStatus.COMPLETED.value,
        solver_status="infeasible",
    )
    db_session.add(exe)
    db_session.commit()
    return exe


def _exhaust_platform_budget(db_session, conv_id):
    PSS.set(db_session, "LLM_MONTHLY_BUDGET_EUR", "0.01")
    db_session.add(
        LLMMessage(
            id=generate_id("msg_"),
            conversation_id=conv_id,
            role="assistant",
            content="costed",
            input_tokens=100,
            output_tokens=100,
            cost_eur=0.10,
            created_at=utcnow().replace(tzinfo=None),
        )
    )
    db_session.commit()
    reset_budget_cache()


def _url(conv_id):
    return f"/api/v2/llm/conversations/{conv_id}/explain-infeasibility"


def test_byok_bypasses_budget_and_charges_no_credits(
    authenticated_client, db_session, test_organization, test_user
):
    conv = _conversation(db_session, test_organization.id, test_user.id)
    exe = _infeasible_execution(db_session, test_organization.id)
    # Seed the platform-budget-exhausting cost in a *separate* conversation so the
    # target conversation ends up with exactly one (BYOK) assistant message.
    budget_conv = _conversation(db_session, test_organization.id, test_user.id)
    _exhaust_platform_budget(db_session, budget_conv.id)

    # Org sets its own key → BYOK-first resolution applies.
    test_organization.anthropic_api_key_encrypted = byok.encrypt_api_key("sk-ant-byok-test-123456")
    db_session.commit()
    credits_before = test_organization.credits_balance

    with patch(
        "app.services.llm.anthropic_client._get_or_create_client",
        return_value=_mock_byok_client(),
    ):
        resp = authenticated_client.post(_url(conv.id), json={"execution_id": exe.id})

    # Budget guardrail bypassed despite the platform budget being exhausted.
    assert resp.status_code == 200, resp.text
    assert "event: done" in resp.text

    db_session.expire_all()
    db_session.refresh(test_organization)
    # No platform credits charged.
    assert test_organization.credits_balance == credits_before
    # Assistant message recorded, but with no platform EUR cost (BYOK spend is the org's).
    assistant = (
        db_session.query(LLMMessage)
        .filter(LLMMessage.conversation_id == conv.id, LLMMessage.role == "assistant")
        .all()
    )
    assert len(assistant) == 1
    assert assistant[0].cost_eur is None


def test_without_byok_budget_exhausted_still_returns_403(
    authenticated_client, db_session, test_organization, test_user
):
    conv = _conversation(db_session, test_organization.id, test_user.id)
    _infeasible_execution(db_session, test_organization.id)
    _exhaust_platform_budget(db_session, conv.id)
    # No BYOK key set → the platform guardrail applies.

    resp = authenticated_client.post(_url(conv.id), json={"formulation": FORMULATION})
    assert resp.status_code == 403
    assert resp.json()["detail"]["reason"] == "llm_monthly_budget_exhausted"
