"""A solve sent with an API key and no origin is recorded as an API run.

# CONTRACT-TEST: an API-key solve that names no origin is stored with origin "api";
# a browser session with no origin stays "manual"; a named origin is kept.

Every solve that named no origin was stored as "manual". Custom Solve in the app
and a script calling ``POST /solve`` with an API key looked the same, so the
execution page could not say where a run came from (QA, 2026-09-25). The origin
``api`` existed in the list of valid origins, and nothing wrote it.
"""

from __future__ import annotations

from app.models import ModelExecution

_LP = {
    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 4}],
    "objective": {"sense": "maximize", "expression": "x"},
    "constraints": [{"name": "c", "expression": "x <= 3"}],
}


def _stored(db_session, response) -> ModelExecution:
    assert response.status_code == 200, response.text
    db_session.expire_all()
    return db_session.get(ModelExecution, response.json()["execution_id"])


def test_an_api_key_solve_with_no_origin_is_an_api_run(authenticated_client, db_session):
    execution = _stored(db_session, authenticated_client.post("/api/v2/solve", json=_LP))
    assert execution.origin == "api"


def test_an_origin_the_caller_names_is_kept(authenticated_client, db_session):
    response = authenticated_client.post("/api/v2/solve?origin=template", json=_LP)
    assert _stored(db_session, response).origin == "template"


def test_a_signed_in_browser_with_no_origin_stays_manual(client, db_session, mock_auth, test_user):
    mock_auth(test_user)
    execution = _stored(db_session, client.post("/api/v2/solve", json=_LP))
    assert execution.origin == "manual"
