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


# CONTRACT-TEST: the JModel DSL ships dark — /dsl/compile is invisible (404, not 403)
# whenever the JAOT_DSL flag is off, so the feature cannot be probed on prod instances.
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


# CONTRACT-TEST: /dsl/compile requires authentication — the compiler is CPU-bound and
# must never be reachable anonymously.
@pytest.mark.integration
def test_compile_requires_auth(client):
    resp = client.post("/api/v2/dsl/compile", json={"source": SMALL_SOURCE})
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.integration
def test_status_requires_auth(client):
    resp = client.get("/api/v2/dsl/status")
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.integration
def test_compile_undefined_set_is_structured_error(
    authenticated_client, test_organization, db_session, enable_dsl
):
    """Regression: `var x{J}` with J undeclared used to escape as a KeyError -> 500."""
    resp = authenticated_client.post(
        "/api/v2/dsl/compile",
        json={"source": "set I := {a};\nvar x{J};\nminimize obj: x[a];"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert "unknown set 'J'" in body["error"]["message"]
    assert body["error"]["position"] is not None


@pytest.mark.integration
def test_compile_error_position_is_exact(
    authenticated_client, test_organization, db_session, enable_dsl
):
    """The editor points at the offending character — the offset must be exact."""
    source = "var x >= 0;\nminimize obj: x + qq;\nsubject to c: x >= 1;"
    resp = authenticated_client.post("/api/v2/dsl/compile", json={"source": source})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["position"] == source.index("qq")


@pytest.mark.integration
def test_compile_internal_error_is_structured_not_500(
    authenticated_client, test_organization, db_session, enable_dsl, monkeypatch
):
    """A compiler bug must surface as ok=false (the editor calls this per keystroke)."""

    def _boom(source):
        raise RuntimeError("compiler bug")

    monkeypatch.setattr("app.api.v2.dsl.compile_jmodel", _boom)
    resp = authenticated_client.post("/api/v2/dsl/compile", json={"source": SMALL_SOURCE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["message"] == "internal compiler error"


@pytest.mark.integration
def test_compile_source_size_cap(authenticated_client, test_organization, db_session, enable_dsl):
    resp = authenticated_client.post(
        "/api/v2/dsl/compile", json={"source": "x" * 1_000_001}
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
def test_gate_cache_serves_stale_within_ttl(db_session, monkeypatch):
    """The production gate path caches the flag for 5s (the test bypass skips it, so
    this exercises the cached branch explicitly with controlled time)."""
    from app.api.v2.deps import dsl_feature_gate as gate

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    now = [1000.0]
    monkeypatch.setattr(gate.time, "monotonic", lambda: now[0])
    monkeypatch.setitem(gate._cache, "value", False)
    monkeypatch.setitem(gate._cache, "expires_at", 0.0)

    PSS.set(db_session, "JAOT_DSL", "true")
    db_session.commit()
    assert gate._is_on(db_session) is True  # fresh read, cached until t+5

    PSS.set(db_session, "JAOT_DSL", "false")
    db_session.commit()
    assert gate._is_on(db_session) is True  # stale-but-within-TTL: cache still serves ON

    now[0] = 1006.0
    assert gate._is_on(db_session) is False  # TTL expired: fresh read sees OFF
