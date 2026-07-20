"""MCP tool-call analytics — the ``MCP_TOOL_CALL`` emitter.

Guards the C1 review-debt fix (v3.1): the emitter that recorded MCP usage lived
on the sync solve path and vanished with the async-only rewrite, pinning the MCP
dashboard at zero. It now wraps fastapi-mcp's single dispatch choke point
(``_execute_api_tool``) so every tool call is counted, attributed to the caller
resolved from the forwarded Bearer.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.mcp import _install_tool_call_analytics, _record_tool_call
from app.models import Organization
from app.models.analytics_event import AnalyticsEvent
from app.shared.constants.event_types import MCP_TOOL_CALL

pytestmark = pytest.mark.contract


def _events(db: Session, org_id: str) -> list[AnalyticsEvent]:
    return (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.org_id == org_id,
            AnalyticsEvent.event_type == MCP_TOOL_CALL,
        )
        .all()
    )


# CONTRACT-TEST: an MCP tool call authenticated by a Bearer API key records an
# MCP_TOOL_CALL event attributed to that principal, tagged with the tool name.
def test_record_tool_call_emits_event(
    client,  # activates the app fixture → SessionLocal bound to the test engine
    db_session: Session,
    test_api_key,
    test_organization: Organization,
):
    info = SimpleNamespace(
        headers={"authorization": f"Bearer {test_api_key.plaintext}"},
    )
    _record_tool_call("solve_problem", info)

    events = _events(db_session, test_organization.id)
    assert len(events) == 1, "one MCP_TOOL_CALL per tool invocation"
    assert events[0].event_metadata["tool"] == "solve_problem"
    assert events[0].user_id == test_api_key.user_id


def test_record_tool_call_without_auth_records_nothing(
    client,
    db_session: Session,
    test_organization: Organization,
):
    _record_tool_call("solve_problem", SimpleNamespace(headers={}))
    _record_tool_call("solve_problem", None)  # context extraction failed upstream
    assert _events(db_session, test_organization.id) == []


def test_record_tool_call_with_bad_key_records_nothing(
    client,
    db_session: Session,
    test_organization: Organization,
):
    info = SimpleNamespace(headers={"authorization": "Bearer ok_live_not_a_real_key"})
    _record_tool_call("solve_problem", info)
    assert _events(db_session, test_organization.id) == []


# CONTRACT-TEST: the wrapper must DELEGATE (return the real tool result) and only
# then record — a bug that swallowed the result would break every MCP tool.
async def test_wrapper_delegates_then_records(
    client,
    db_session: Session,
    test_api_key,
    test_organization: Organization,
):
    class _FakeMcp:
        def __init__(self) -> None:
            self.seen: list[str] = []

        async def _execute_api_tool(
            self,
            *,
            client=None,
            tool_name=None,
            arguments=None,
            operation_map=None,
            http_request_info=None,
        ):
            self.seen.append(tool_name)
            return ["tool-result"]

    fake = _FakeMcp()
    _install_tool_call_analytics(fake)

    info = SimpleNamespace(headers={"authorization": f"Bearer {test_api_key.plaintext}"})
    result = await fake._execute_api_tool(
        client=None,
        tool_name="get_execution",
        arguments={},
        operation_map={},
        http_request_info=info,
    )

    assert result == ["tool-result"], "wrapper must return the underlying tool result"
    assert fake.seen == ["get_execution"], "underlying dispatch must still run exactly once"
    events = _events(db_session, test_organization.id)
    assert len(events) == 1
    assert events[0].event_metadata["tool"] == "get_execution"
