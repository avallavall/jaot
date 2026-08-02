"""The MCP handshake must report a version, not the server description."""

import pytest

from app.main import create_app


@pytest.mark.unit
def test_mcp_handshake_reports_version_and_instructions() -> None:
    """# CONTRACT-TEST: serverInfo.version is the app version, never the description."""
    app = create_app()
    mcp = app.state.mcp if hasattr(app.state, "mcp") else None
    from app.mcp import setup_mcp

    mcp = mcp or setup_mcp(app)
    server = mcp.server

    assert server.version == app.version, (
        f"serverInfo.version is {server.version!r}; fastapi-mcp puts the description here"
    )
    assert len(server.version) < 32, "a version is short; a description is not"
    assert server.instructions == mcp.description, (
        "the description belongs in instructions — that is what a client model reads"
    )
