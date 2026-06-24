"""Tests for solve_maintenance_gate dependency (Phase 6 D-19 / INF-04).

Verify that enabling the SOLVE_MAINTENANCE_MODE platform setting rejects
new solves with 503 + Retry-After: 600 while leaving non-solve routes
(reads, auth, validation) available. This is the granular kill-switch
used by deploy.sh multi_solver_rotate during the drain+rotate window.
"""

import pytest

from app.services.platform_settings_service import PlatformSettingsService as PSS

SMALL_PROBLEM = {
    "name": "gate_test",
    "objective": {"sense": "maximize", "expression": "x"},
    "variables": [
        {
            "name": "x",
            "type": "continuous",
            "lower_bound": 0,
            "upper_bound": 10,
        },
    ],
    "constraints": [],
}


@pytest.fixture
def enable_solve_maintenance(db_session):
    """Turn SOLVE_MAINTENANCE_MODE ON for a single test, then restore OFF.

    Uses the shared db_session (SAVEPOINT pattern) so the setting is
    visible to the FastAPI dependency which reads via the same session
    (see ``_override_db_dependency`` autouse in conftest).
    """
    PSS.set(db_session, "SOLVE_MAINTENANCE_MODE", "true")
    db_session.commit()
    yield
    PSS.set(db_session, "SOLVE_MAINTENANCE_MODE", "false")
    db_session.commit()


@pytest.mark.integration
def test_flag_off_allows_solve_async(authenticated_client, test_organization, db_session):
    """Default state (flag=false): the gate must NOT fire.

    The contract under test is narrow: `solve_maintenance_gate` (the
    `error: "solve_maintenance"` discriminator) does not short-circuit
    the request when the flag is off. The endpoint itself may still
    return 500/503 from infrastructure failures (DB flap, exhausted
    pool under load, network partition) — those are a separate
    reliability concern and have nothing to say about the gate.

    Assertion: if 503 is returned, the error code must not be
    `solve_maintenance` — any other error code (including the
    middleware's generic `service_unavailable`) is by definition
    NOT a gate misfire.
    """
    resp = authenticated_client.post("/api/v2/solve/async", json=SMALL_PROBLEM)
    if resp.status_code == 503:
        body = resp.json()
        # FastAPI HTTPException detail wraps the payload under "detail";
        # the ASGI middleware returns the payload at the top level.
        detail = body.get("detail", body) if isinstance(body, dict) else {}
        assert detail.get("error") != "solve_maintenance", (
            f"Gate fired while flag is off — this is the real bug this test catches: {resp.text}"
        )


@pytest.mark.integration
def test_flag_on_blocks_solve_async(
    authenticated_client,
    test_organization,
    db_session,
    enable_solve_maintenance,
):
    """D-19: POST /solve/async returns 503 + Retry-After: 600 when flag on."""
    resp = authenticated_client.post("/api/v2/solve/async", json=SMALL_PROBLEM)

    assert resp.status_code == 503, resp.text
    assert resp.headers.get("retry-after") == "600"

    body = resp.json()
    detail = body["detail"]
    assert detail["error"] == "solve_maintenance"
    assert "maintenance" in detail["message"].lower()


@pytest.mark.integration
def test_flag_on_blocks_solve_sync(
    authenticated_client,
    test_organization,
    db_session,
    enable_solve_maintenance,
):
    """POST /solve (sync) also gated (dependency runs before handler)."""
    resp = authenticated_client.post("/api/v2/solve", json=SMALL_PROBLEM)

    assert resp.status_code == 503, resp.text
    assert resp.headers.get("retry-after") == "600"


@pytest.mark.integration
def test_flag_on_blocks_model_execute(
    authenticated_client,
    test_organization,
    db_session,
    enable_solve_maintenance,
):
    """POST /models/{id}/execute also gated.

    Use a non-existent model id — the gate fires BEFORE the 404 because
    FastAPI runs route dependencies before the handler body.
    """
    resp = authenticated_client.post(
        "/api/v2/models/mdl_nonexistent/execute",
        json={"input_data": {}},
    )

    assert resp.status_code == 503, resp.text
    assert resp.headers.get("retry-after") == "600"


@pytest.mark.integration
def test_flag_on_does_NOT_block_read_routes(
    authenticated_client,
    test_organization,
    db_session,
    enable_solve_maintenance,
):
    """GET routes and non-solve endpoints must remain available.

    The gate is scoped to solve-family POST routes only, unlike the
    existing global MaintenanceMiddleware. This is the whole reason we
    chose a dependency over extending the middleware (RESEARCH.md
    Open Question 3).
    """
    # /api/v2/models (GET) must not be gated by a solve-only flag.
    resp = authenticated_client.get("/api/v2/models")
    assert resp.status_code != 503, resp.text


@pytest.mark.integration
def test_flag_on_does_NOT_block_validate(
    authenticated_client,
    test_organization,
    db_session,
    enable_solve_maintenance,
):
    """POST /solve/validate is NOT a solve — it must remain available.

    Validation is a read-only check with no solver dispatch; the gate
    explicitly exempts it so users can keep validating problems while
    the worker fleet is being rotated.
    """
    resp = authenticated_client.post("/api/v2/solve/validate", json=SMALL_PROBLEM)
    assert resp.status_code != 503, resp.text


@pytest.mark.integration
def test_503_body_shape(
    authenticated_client,
    test_organization,
    db_session,
    enable_solve_maintenance,
):
    """503 response body shape is stable for client-side retry logic."""
    resp = authenticated_client.post("/api/v2/solve/async", json=SMALL_PROBLEM)

    assert resp.status_code == 503
    body = resp.json()
    # Envelope must carry a ``detail`` dict with the two required keys.
    assert isinstance(body.get("detail"), dict)
    assert body["detail"].get("error") == "solve_maintenance"
    assert isinstance(body["detail"].get("message"), str)
    assert body["detail"]["message"]  # non-empty
