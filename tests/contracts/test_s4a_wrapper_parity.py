"""ADR-007 S4a — parity contracts for the wrapper endpoints that now ride the ONE
async pipeline: ``POST /projects/{id}/solve``, ``POST /import``, and
``POST /solve/templates/{id}/solve``.

# CONTRACT-TEST: each wrapper returns the classic sync ``OptimizationResult``
contract on completion (execution_id + credits_used + credits_remaining injected),
degrades to 202 past the wait budget, and preserves the endpoint-specific side
effect the old orchestrator path carried (the TEMPLATE_USE analytics event). If
these break, the S4a conversion changed the observable contract.

The async task runs EAGERLY via the autouse ``eager_solve_async_pipeline`` fixture
(real SCIP, real DB, real refunds), so the observed payload is the genuine worker
envelope reshaped by the wait wrapper — never a stub.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.domains.solver.tasks.solve_tasks as solve_tasks_mod
from app.models import Organization
from app.models.analytics_event import AnalyticsEvent

pytestmark = pytest.mark.contract

_KNAPSACK_INPUT = {
    "capacity": 50,
    "items": [
        {"name": "laptop", "value": 600, "weight": 10},
        {"name": "camera", "value": 500, "weight": 5},
    ],
}

# The four fields the sync orchestrator used to inject that the async envelope does
# not carry natively — the wait wrapper must add them back.
_SYNC_RESULT_KEYS = {"status", "execution_id", "credits_used", "credits_remaining"}


def _fund(db: Session, org: Organization) -> None:
    db.query(Organization).filter(Organization.id == org.id).update({"credits_balance": 1_000_000})
    db.commit()


class TestTemplateWrapperParity:
    """The template solve rides ``_enqueue_async_solve`` yet must look sync."""

    def test_template_solve_returns_sync_result_shape(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
    ):
        _fund(db_session, test_organization)
        res = authenticated_client.post(
            "/api/v2/solve/templates/knapsack/solve", json=_KNAPSACK_INPUT
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert _SYNC_RESULT_KEYS <= set(body)
        assert body["execution_id"].startswith("exe_")
        assert body["status"] in ("optimal", "feasible")
        # A real answer is charged; the balance is a concrete int.
        assert body["credits_used"] >= 1
        assert isinstance(body["credits_remaining"], int)

    # CONTRACT-TEST: the TEMPLATE_USE analytics event the old orchestrator fired must
    # survive the async-only conversion (template-popularity analytics). It is the ONE
    # side effect the shared async pipeline does not carry, so the wrapper re-fires it.
    def test_template_solve_still_logs_template_use(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
    ):
        _fund(db_session, test_organization)
        res = authenticated_client.post(
            "/api/v2/solve/templates/knapsack/solve", json=_KNAPSACK_INPUT
        )
        assert res.status_code == 200, res.text
        event = (
            db_session.query(AnalyticsEvent)
            .filter(
                AnalyticsEvent.org_id == test_organization.id,
                AnalyticsEvent.event_type == "template.use",
            )
            .first()
        )
        assert event is not None, "template solve must log a TEMPLATE_USE analytics event"
        assert event.event_metadata["template_id"] == "knapsack"


class TestWrapperWaitDegradation:
    """A slow wrapper solve degrades to 202 + envelope instead of blocking to a proxy
    or orchestrator timeout (the observable win of the async-under-the-hood contract)."""

    # CONTRACT-TEST: template wrapper past the wait budget → 202 + task envelope.
    def test_template_solve_degrades_to_202(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        monkeypatch,
    ):
        from celery.exceptions import TimeoutError as CeleryTimeoutError

        _fund(db_session, test_organization)

        class _NeverDone:
            id = "s4a-wait-timeout-task"

            def get(self, **kwargs):
                raise CeleryTimeoutError("still running")

        # Overrides the autouse eager patch (this monkeypatch runs later, so it wins).
        monkeypatch.setattr(solve_tasks_mod.solve_async, "apply_async", lambda **opts: _NeverDone())

        res = authenticated_client.post(
            "/api/v2/solve/templates/knapsack/solve", json=_KNAPSACK_INPUT
        )
        assert res.status_code == 202, res.text
        body = res.json()
        assert body["task_id"] == "s4a-wait-timeout-task"
        assert body["execution_id"].startswith("exe_")
        assert body["status"] == "pending"
        assert body["poll_url"].endswith(body["task_id"])
