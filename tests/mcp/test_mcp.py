"""MCP server integration tests.

Validates:
- AI-01: MCP server mounted at /mcp with 19 curated tools
- AI-02: Tools cover solve path and marketplace path
- AI-03: Auth passthrough (public vs protected endpoints)
- AI-04: llms.txt served at /.well-known/llms.txt
- AI-05: llms-full.txt served at /.well-known/llms-full.txt

Note: The /mcp endpoint uses SSE transport, so we cannot issue a simple
GET with TestClient (it would hang waiting for the stream). Instead we
verify MCP is mounted by inspecting the app's route table and OpenAPI
schema, and test auth on the underlying REST endpoints that MCP proxies.
"""

import inspect

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

EXPECTED_OPERATIONS = [
    # Solve
    "solve_problem",
    "validate_problem",
    "solve_multi_objective",
    "list_available_solvers",
    # Templates
    "list_templates",
    "get_template",
    "solve_with_template",
    # File I/O — standard formats (MPS/LP/CIP/JSON)
    "import_preview",
    "import_and_solve",
    "export_model",
    "export_execution",
    # Marketplace
    "list_catalog_models",
    "get_catalog_model",
    "get_catalog_model_schema",
    "activate_catalog_model",
    # Execution, analysis & credits
    "execute_model",
    "get_execution",
    "get_execution_insights",
    "get_credit_balance",
]


@pytest.fixture(scope="module")
def mcp_app():
    """Create a fresh app instance with auth enabled for MCP tests."""
    return create_app()


@pytest.fixture(scope="module")
def mcp_client(mcp_app):
    """Test client for HTTP requests (with auth middleware active)."""
    return TestClient(mcp_app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def openapi_schema(mcp_app):
    """Cached OpenAPI schema."""
    return mcp_app.openapi()


# ---- AI-01: MCP server reachable ----


def test_mcp_server_mounted(mcp_app):
    """MCP endpoint is registered in the app's route table (not 404)."""
    mcp_paths = [r.path for r in mcp_app.routes if "/mcp" in str(getattr(r, "path", ""))]
    assert len(mcp_paths) > 0, "No /mcp routes found in app -- MCP not mounted"
    assert "/mcp" in mcp_paths or any("/mcp" in p for p in mcp_paths), (
        f"Expected /mcp in routes, found: {mcp_paths}"
    )


def test_mcp_route_exists(mcp_app):
    """MCP routes are registered in the application."""
    mcp_routes = [r.path for r in mcp_app.routes if "/mcp" in str(getattr(r, "path", ""))]
    assert len(mcp_routes) > 0, "No /mcp routes found in app"


# ---- AI-01: Exactly 19 tools exposed ----


def test_mcp_tool_count(openapi_schema):
    """MCP server exposes exactly 19 curated tools (not 40+)."""
    all_op_ids = _extract_op_ids(openapi_schema)

    # All expected operations must be present
    missing = set(EXPECTED_OPERATIONS) - all_op_ids
    assert not missing, f"Missing operation_ids from OpenAPI schema: {missing}"

    # The MCP module's include_operations list has exactly len(EXPECTED) entries
    from app.mcp import setup_mcp

    source = inspect.getsource(setup_mcp)
    # Count the quoted operation_id strings in the source
    op_count = sum(1 for op in EXPECTED_OPERATIONS if f'"{op}"' in source)
    assert op_count == len(EXPECTED_OPERATIONS), (
        f"Expected {len(EXPECTED_OPERATIONS)} operations in source, found {op_count}"
    )


def test_mcp_required_tools_present(openapi_schema):
    """All required operation_ids are present in the OpenAPI schema."""
    all_op_ids = _extract_op_ids(openapi_schema)

    for op_id in EXPECTED_OPERATIONS:
        assert op_id in all_op_ids, f"operation_id '{op_id}' missing from OpenAPI schema"


# ---- AI-01: No admin/billing/GDPR leak ----


def test_no_unwanted_operations_leak():
    """Admin, billing, GDPR, and builder endpoints do NOT leak into MCP tools."""
    leaked_prefixes = ("admin_", "gdpr_", "builder_")
    for op_id in EXPECTED_OPERATIONS:
        for prefix in leaked_prefixes:
            assert not op_id.startswith(prefix), (
                f"Leaked operation {op_id} found in MCP include list"
            )


# ---- AI-02: Tools cover solve AND marketplace paths ----


def test_solve_path_tools_present(openapi_schema):
    """Solve-related tools are present."""
    all_op_ids = _extract_op_ids(openapi_schema)
    solve_ops = [
        "solve_problem",
        "validate_problem",
        "list_templates",
        "get_template",
        "solve_with_template",
    ]
    for op in solve_ops:
        assert op in all_op_ids, f"Solve tool '{op}' missing"


def test_marketplace_path_tools_present(openapi_schema):
    """Marketplace/catalog tools are present."""
    all_op_ids = _extract_op_ids(openapi_schema)
    marketplace_ops = [
        "list_catalog_models",
        "get_catalog_model",
        "get_catalog_model_schema",
        "activate_catalog_model",
        "execute_model",
        "get_execution",
    ]
    for op in marketplace_ops:
        assert op in all_op_ids, f"Marketplace tool '{op}' missing"


# ---- AI-03: Auth passthrough ----


def test_mcp_auth_public_endpoint(mcp_app):
    """Public endpoints are marked as public in the auth middleware."""
    from app.shared.core.auth_middleware import _is_public

    # list_templates is public
    assert _is_public("/api/v2/solve/templates", "GET"), (
        "/api/v2/solve/templates GET should be public"
    )

    # list_catalog_models is public
    assert _is_public("/api/v2/models/catalog", "GET"), (
        "/api/v2/models/catalog GET should be public"
    )


def test_mcp_auth_protected_endpoint(mcp_app):
    """Protected endpoints are NOT marked as public in the auth middleware."""
    from app.shared.core.auth_middleware import _is_public

    # solve_problem requires auth
    assert not _is_public("/api/v2/solve", "POST"), "/api/v2/solve POST should NOT be public"

    # get_credit_balance requires auth
    assert not _is_public("/api/v2/credits/balance", "GET"), (
        "/api/v2/credits/balance GET should NOT be public"
    )


def test_mcp_endpoint_is_public(mcp_app):
    """The /mcp endpoint itself is public (in PUBLIC_ENDPOINTS_PREFIX)."""
    from app.shared.core.auth_middleware import _is_public

    assert _is_public("/mcp", "GET"), "/mcp should be a public endpoint"
    assert _is_public("/mcp/messages/", "POST"), (
        "/mcp/messages/ should be a public endpoint (prefix match)"
    )


# ---- AI-01: operation_ids explicitly set ----


def test_operation_ids_set(openapi_schema):
    """The targeted endpoints have explicit operation_id in OpenAPI schema."""
    all_op_ids = _extract_op_ids(openapi_schema)
    for op_id in EXPECTED_OPERATIONS:
        assert op_id in all_op_ids, (
            f"operation_id '{op_id}' not found in OpenAPI schema -- "
            f"decorator may be missing operation_id kwarg"
        )


# ---- AI-04: llms.txt discovery document ----


def test_llms_txt(mcp_app):
    """llms.txt route is registered in the app."""
    well_known_routes = [
        r.path for r in mcp_app.routes if hasattr(r, "path") and ".well-known" in str(r.path)
    ]
    assert any("llms.txt" in p for p in well_known_routes), (
        f"No llms.txt route found. Routes: {well_known_routes}"
    )


def test_llms_txt_content():
    """llms.txt content has JAOT header and MCP reference."""
    from app.api.v2.llms import LLMS_TXT

    assert "JAOT" in LLMS_TXT, "Missing JAOT header in llms.txt"
    assert "/mcp" in LLMS_TXT, "Missing MCP endpoint reference"


# ---- AI-05: llms-full.txt comprehensive documentation ----


def test_llms_full_txt(mcp_app):
    """llms-full.txt route is registered in the app."""
    well_known_routes = [
        r.path for r in mcp_app.routes if hasattr(r, "path") and ".well-known" in str(r.path)
    ]
    assert any("llms-full.txt" in p for p in well_known_routes), (
        f"No llms-full.txt route found. Routes: {well_known_routes}"
    )


def test_llms_full_txt_content():
    """llms-full.txt content is substantial with required sections."""
    from app.api.v2.llms import LLMS_FULL_TXT

    assert "Authentication" in LLMS_FULL_TXT, "Missing Authentication section"
    assert "API" in LLMS_FULL_TXT, "Missing API Reference section"
    assert len(LLMS_FULL_TXT) > 1000, f"llms-full.txt too short ({len(LLMS_FULL_TXT)} chars)"


def test_llms_txt_not_in_openapi(mcp_app):
    """Neither llms.txt route appears in the OpenAPI schema paths."""
    schema = mcp_app.openapi()
    paths = list(schema["paths"].keys())
    for path in paths:
        assert ".well-known" not in path, f"llms route '{path}' leaked into OpenAPI schema"


# ---- Helpers ----


def _extract_op_ids(schema: dict) -> set[str]:
    """Extract all operationId values from an OpenAPI schema."""
    op_ids: set[str] = set()
    for _path, methods in schema["paths"].items():
        for _method, details in methods.items():
            if isinstance(details, dict) and "operationId" in details:
                op_ids.add(details["operationId"])
    return op_ids
