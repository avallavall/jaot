"""Tests for the JModel DSL endpoints (P5.2).

Covers the JAOT_DSL feature gate (404 when off), the status probe, successful
compilation, structured compile errors, and auth. Mirrors the toggling pattern in
``test_solve_maintenance_gate.py`` (PSS.set on the shared db_session).
"""

import pytest

from app.services.platform_settings_service import PlatformSettingsService as PSS

SMALL_SOURCE = """
var x >= 0;
minimize obj: x;
subject to c: x >= 5;
"""


@pytest.fixture
def enable_dsl(db_session):
    """Turn JAOT_DSL ON for a single test, then restore OFF."""
    PSS.set(db_session, "JAOT_DSL", "true")
    db_session.commit()
    yield
    PSS.set(db_session, "JAOT_DSL", "false")
    db_session.commit()


@pytest.mark.integration
def test_status_disabled_by_default(authenticated_client, test_organization, db_session):
    resp = authenticated_client.get("/api/v2/dsl/status")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": False}


@pytest.mark.integration
def test_status_enabled_when_flag_on(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.get("/api/v2/dsl/status")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": True}


@pytest.mark.integration
def test_compile_404_when_flag_off(authenticated_client, test_organization, db_session):
    """The compile endpoint is invisible (404) while the feature ships dark."""
    resp = authenticated_client.post("/api/v2/dsl/compile", json={"source": SMALL_SOURCE})
    assert resp.status_code == 404, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "dsl_disabled"


@pytest.mark.integration
def test_compile_ok_when_flag_on(authenticated_client, test_organization, db_session, enable_dsl):
    resp = authenticated_client.post("/api/v2/dsl/compile", json={"source": SMALL_SOURCE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["error"] is None
    problem = body["problem"]
    assert [v["name"] for v in problem["variables"]] == ["x"]
    assert problem["objective"]["expression"] == "x"
    assert problem["constraints"][0]["expression"] == "x >= 5"


@pytest.mark.integration
def test_compile_reports_structured_error(
    authenticated_client, test_organization, db_session, enable_dsl
):
    """A syntax error is a 200 with ok=false + message + position (no 4xx)."""
    resp = authenticated_client.post(
        "/api/v2/dsl/compile",
        json={"source": "set S := {a, b}\nvar x >= 0;"},  # missing ';' after the set
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["problem"] is None
    assert body["error"]["message"]
    assert body["error"]["position"] is not None


@pytest.mark.integration
def test_compile_unknown_symbol_error(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.post(
        "/api/v2/dsl/compile",
        json={"source": "var x >= 0; minimize obj: x + y; subject to c: x >= 1;"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert "unknown symbol" in body["error"]["message"]


@pytest.mark.integration
def test_compile_requires_auth(client):
    resp = client.post("/api/v2/dsl/compile", json={"source": SMALL_SOURCE})
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.integration
def test_status_requires_auth(client):
    resp = client.get("/api/v2/dsl/status")
    assert resp.status_code in (401, 403), resp.text
