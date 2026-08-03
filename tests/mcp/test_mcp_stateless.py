"""The MCP HTTP transport must work under multiple uvicorn workers.

fastapi-mcp 0.4.0 keeps MCP sessions in a per-process dict. Production runs
several workers, so a request whose ``mcp-session-id`` landed on a different
worker than the one that answered ``initialize`` got 404 "Session not found" —
measured against production: calls separated by realistic pauses failed 3 out
of 4 with 4 workers. The fix (``_force_stateless_http``) flips the SDK's
session manager to stateless: no session id is issued, and a stale session
header from a client mid-rollout is simply ignored.

These tests drive the real JSON-RPC surface at /mcp. A TestClient used as a
context manager keeps one event loop alive across requests, which the lazily
started session manager needs.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}

TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


@pytest.fixture(scope="module")
def mcp_app():
    return create_app()


@pytest.fixture(scope="module")
def mcp_client(mcp_app):
    with TestClient(mcp_app, raise_server_exceptions=False) as client:
        yield client


def test_initialize_issues_no_session_id(mcp_client):
    """# CONTRACT-TEST: stateless MCP never issues a session id — a session id
    minted by one worker is a 404 on the other workers."""
    response = mcp_client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)

    assert response.status_code == 200, response.text
    assert "mcp-session-id" not in response.headers, (
        "initialize issued a session id: sessions live in one worker's memory, "
        "so any follow-up landing on another worker gets 404 Session not found"
    )
    result = response.json()["result"]
    assert result["serverInfo"]["name"] == "JAOT Optimization Platform"


def test_tool_listing_needs_no_prior_handshake(mcp_client):
    """Each request is self-contained: a worker that never saw this client's
    ``initialize`` must still serve it (that is what multi-worker means)."""
    response = mcp_client.post("/mcp", json=TOOLS_LIST, headers=MCP_HEADERS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body
    tool_names = {tool["name"] for tool in body["result"]["tools"]}
    assert "solve_problem" in tool_names


def test_stale_session_header_is_ignored(mcp_client):
    """# CONTRACT-TEST: a session id the server does not know is ignored, not
    404 — the exact production failure signature under 4 workers."""
    headers = {**MCP_HEADERS, "mcp-session-id": "deadbeefdeadbeefdeadbeefdeadbeef"}
    response = mcp_client.post("/mcp", json=TOOLS_LIST, headers=headers)

    assert response.status_code == 200, (
        f"got {response.status_code}: {response.text} — the per-worker session "
        "dict is back; every real client fails 3 out of 4 calls"
    )
    assert "error" not in response.json()


def test_session_manager_runs_stateless(mcp_client, mcp_app):
    """The SDK manager itself carries stateless=True once started, so dispatch
    never consults the per-process session dict."""
    # The manager starts lazily on the first request; the tests above have
    # already driven one. Reach the transport through the mounted route's
    # closure — fastapi-mcp keeps no public handle to it.
    routes = [r for r in mcp_app.routes if getattr(r, "path", "") == "/mcp"]
    assert routes, "MCP route not mounted"
    transport = next(
        cell.cell_contents
        for cell in routes[0].endpoint.__closure__
        if hasattr(cell.cell_contents, "_session_manager")
    )
    manager = transport._session_manager
    assert manager is not None, "session manager never started"
    assert manager.stateless is True, (
        "manager is session-bound: sessions live in one worker's dict and the "
        "other workers answer 404 Session not found"
    )
