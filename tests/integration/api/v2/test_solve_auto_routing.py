"""Integration tests for solver_name='auto' routing — Phase 7.4 / D-11.

Platform-license model: auto-routing uses the Hexaly worker health probe
(not SolverLicense DB rows). Tests verify the dispatch decision is reflected
in ``solver_used`` + ``auto_route_reason`` on the /api/v2/solve response.

Covers:
    Auto-routing dispatch (D-11 / D-07 post-7.4):
        - "auto" + pure-LP -> solver_used="highs" + reason="lp_routed_to_highs"
        - "auto" + quadratic + worker UP -> solver_used="hexaly"
          + reason="quadratic_routed_to_hexaly" (or 422 if SDK absent)
        - "auto" + quadratic + worker DOWN -> solver_used="scip"
          + reason="hexaly_unavailable_fallback" + warning present

Tests run against real PostgreSQL (``jaot_test``). No SolverLicense rows
needed — routing is determined by worker health only.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.user import User
from app.services.auth.api_key_service import APIKeyService
from tests.conftest import _AuthClient

_LP_BODY = {
    "solver_name": "auto",
    "name": "auto_lp",
    "objective": {"sense": "maximize", "expression": "2*x + 3*y"},
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0.0, "upper_bound": 10.0},
        {"name": "y", "type": "continuous", "lower_bound": 0.0, "upper_bound": 10.0},
    ],
    "constraints": [{"name": "budget", "expression": "x + y <= 5"}],
    "options": {"time_limit_seconds": 5},
}

_QUADRATIC_BODY = {
    "solver_name": "auto",
    "name": "auto_quadratic",
    "objective": {"sense": "maximize", "expression": "x * y"},
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0.0, "upper_bound": 10.0},
        {"name": "y", "type": "continuous", "lower_bound": 0.0, "upper_bound": 10.0},
    ],
    "constraints": [{"name": "budget", "expression": "x + y <= 10"}],
    "options": {"time_limit_seconds": 5},
}

# Patch the source-level probe in worker_health so both the auto-router
# decision (auto_router._is_hexaly_worker_available is a thin wrapper) and
# the post-routing availability gate (ensure_hexaly_worker_or_503 calls
# _probe_hexaly_worker directly) see the same mocked state. Mocking only the
# wrapper lets the gate fire 503 because its independent probe still finds
# no real worker.
_WORKER_PROBE = "app.domains.solver.services.worker_health._probe_hexaly_worker"


def _build_org_with_owner(db: Session, org_id: str, user_id: str) -> tuple[Organization, User, str]:
    """Build an org with a credit balance + an owner User + an API key.

    Uses ``flush()`` for intermediate writes so each fixture call pays one
    final fsync (via ``APIKeyService.create_api_key``) instead of four.
    """
    org = Organization(
        id=org_id,
        name=f"Auto Routing Co {org_id}",
        credits_balance=1000,
        is_active=True,
        rate_limit_per_minute=999_999,
        rate_limit_per_day=999_999,
    )
    db.add(org)
    db.flush()
    user = User(
        id=user_id,
        email=f"{user_id}@auto.test",
        name=f"Auto Owner {user_id}",
        organization_id=org.id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    org.owner_user_id = user.id
    db.flush()
    # APIKeyService.create_api_key issues its own commit — covers everything above.
    _api_key_row, plaintext = APIKeyService.create_api_key(
        db=db,
        user_id=user.id,
        organization_id=org.id,
        name=f"Key {user_id}",
        prefix="ok_test_",
    )
    return org, user, plaintext


@pytest.fixture
def auto_owner_setup(db_session):
    """Returns ``(org, user, plaintext)`` for the authenticated owner."""
    return _build_org_with_owner(db_session, "org_auto_own1", "usr_auto_own1")


@pytest.fixture
def auto_owner_org(auto_owner_setup):
    """Returns ``(org, user)`` — projection over auto_owner_setup."""
    org, user, _plaintext = auto_owner_setup
    return org, user


@pytest.fixture
def auto_owner_client(client, auto_owner_setup):
    """Authenticated client whose user owns ``auto_owner_org``."""
    _org, _user, plaintext = auto_owner_setup
    return _AuthClient(client, plaintext)


# Auto-routing dispatch tests (D-11 / worker-health-probe based)


def test_solve_with_auto_lp_routes_to_highs(auto_owner_client):
    """auto + pure-LP -> solver_used='highs' + reason='lp_routed_to_highs'.

    LP detection is purely structural (all CONTINUOUS + linear terms) —
    no worker probe invoked for LP; this test requires no mock.
    """
    r = auto_owner_client.post("/api/v2/solve", json=_LP_BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["solver_used"] == "highs"
    assert body["auto_route_reason"] == "lp_routed_to_highs"


def test_solve_with_auto_quadratic_worker_down_routes_to_scip(auto_owner_client):
    """auto + quadratic + Hexaly worker DOWN -> solver_used='scip' + fallback warning.

    Phase 7.4 / D-11: when the worker is unavailable the router falls back
    to SCIP and surfaces a warning field. No SolverLicense DB row needed.
    """
    with patch(_WORKER_PROBE, return_value=(False, "test_off")):
        r = auto_owner_client.post("/api/v2/solve", json=_QUADRATIC_BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["solver_used"] == "scip"
    assert body["auto_route_reason"] == "hexaly_unavailable_fallback"
    assert body.get("warning"), "D-11: fallback must surface a warning field"


def test_solve_with_auto_quadratic_worker_up_attempts_hexaly(auto_owner_client):
    """auto + quadratic + Hexaly worker UP -> dispatch target is 'hexaly'.

    We accept 200 (successful hexaly solve) OR 422 (SolverNotFoundError
    when the hexaly adapter is not registered in this environment). Either
    way we verify no BYOL-era gate error ('license_not_found', etc.) fires.
    """
    with patch(_WORKER_PROBE, return_value=(True, None)):
        r = auto_owner_client.post("/api/v2/solve", json=_QUADRATIC_BODY)

    if r.status_code == 200:
        body = r.json()
        assert body["solver_used"] == "hexaly"
        assert body["auto_route_reason"] == "quadratic_routed_to_hexaly"
    else:
        # 422 from dispatch layer — adapter not registered on this worker.
        assert r.status_code == 422
        detail = str(r.json().get("detail", ""))
        assert "license_not_found" not in detail
        assert "license_expired" not in detail
