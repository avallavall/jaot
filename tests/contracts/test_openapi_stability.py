"""Contract tests for the FastAPI OpenAPI schema.

These tests guard the cross-layer contract between backend and frontend:
the OpenAPI schema is the source of truth that generates
``frontend/src/lib/generated/api.ts``. Any drift here silently breaks the
frontend type-check at build time.

Scope (backend invariants only — TS drift is detected by
``npm run check-types`` in CI):

1. The schema generates successfully from ``app.main:app``.
2. The schema is OpenAPI 3.x and structurally valid.
3. Every ``operationId`` is unique (required by ``openapi-typescript``).
4. Critical endpoints that the frontend depends on are present with the
   expected HTTP method.
5. Every documented path has at least one ``tag`` (enables grouped TS types).

If a test fails: either you broke the contract (fix the code), or the
contract genuinely changed (update this file in the same PR as the
frontend ``api.ts`` regeneration).
"""

from __future__ import annotations

import pytest

from app.main import app


@pytest.fixture(scope="module")
def openapi_schema() -> dict:
    """Generate the OpenAPI schema once per test module."""
    return app.openapi()


def test_openapi_schema_generates(openapi_schema: dict) -> None:
    """Schema generation must not raise and must produce a non-empty dict."""
    assert isinstance(openapi_schema, dict)
    assert openapi_schema, "OpenAPI schema is empty"


def test_openapi_version_is_3x(openapi_schema: dict) -> None:
    """openapi-typescript requires OpenAPI 3.x."""
    version = openapi_schema.get("openapi", "")
    assert version.startswith("3."), f"Expected OpenAPI 3.x, got {version!r}"


def test_openapi_has_paths_and_components(openapi_schema: dict) -> None:
    """A valid schema must expose paths and component schemas."""
    assert "paths" in openapi_schema, "Schema missing 'paths'"
    assert openapi_schema["paths"], "Schema has zero paths"
    assert "components" in openapi_schema, "Schema missing 'components'"
    assert "schemas" in openapi_schema["components"], "Schema missing component schemas"


def test_operation_ids_are_unique(openapi_schema: dict) -> None:
    """openapi-typescript generates deduplicated types keyed by operationId.

    Duplicate operationIds cause silent type collisions in the frontend —
    both operations map to the same generated type.
    """
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []

    for path, methods in openapi_schema["paths"].items():
        for method, op in methods.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            op_id = op.get("operationId")
            if op_id is None:
                continue
            if op_id in seen:
                duplicates.append((op_id, seen[op_id], f"{method.upper()} {path}"))
            else:
                seen[op_id] = f"{method.upper()} {path}"

    assert not duplicates, (
        "Duplicate operationIds detected (breaks TS type generation):\n"
        + "\n".join(f"  {op_id}: {first} vs {second}" for op_id, first, second in duplicates)
    )


# Endpoints the frontend explicitly depends on. Breaking these without a
# coordinated frontend PR ships a broken UI.
CORE_ENDPOINTS: list[tuple[str, str]] = [
    ("POST", "/api/v2/auth/login"),
    ("POST", "/api/v2/auth/signup"),
    ("POST", "/api/v2/auth/refresh"),
    ("GET", "/api/v2/health"),
    ("GET", "/api/v2/models/catalog"),
    ("POST", "/api/v2/solve/validate"),
    ("GET", "/api/v2/solve/templates"),
    ("GET", "/api/v2/credits/rates"),
]


@pytest.mark.parametrize(("method", "path"), CORE_ENDPOINTS)
def test_core_endpoint_exists(openapi_schema: dict, method: str, path: str) -> None:
    """Each frontend-critical endpoint must be present with the expected method."""
    paths = openapi_schema["paths"]
    assert path in paths, f"Core endpoint missing from schema: {path}"
    methods = {m.lower() for m in paths[path] if not m.startswith("x-")}
    assert method.lower() in methods, (
        f"Core endpoint {path} missing {method} (present methods: {sorted(methods)})"
    )


def test_every_path_is_tagged(openapi_schema: dict) -> None:
    """openapi-typescript groups generated types by tag.

    An untagged endpoint lands in an 'untagged' bucket and is hard to
    discover in the frontend. Every route registered via ``include_router``
    already carries a tag — this test fails loud if someone adds a route
    without one.
    """
    untagged: list[str] = []
    for path, methods in openapi_schema["paths"].items():
        for method, op in methods.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            if not op.get("tags"):
                untagged.append(f"{method.upper()} {path}")

    assert not untagged, "Operations missing tags (breaks grouped TS generation):\n" + "\n".join(
        f"  {entry}" for entry in untagged
    )


def test_schema_is_deterministic() -> None:
    """Generating the schema twice must yield identical output.

    Non-determinism (e.g. unsorted dicts, random IDs, timestamps in the
    schema) silently causes ``api.ts`` drift on every regeneration.
    """
    first = app.openapi()
    # Reset cached schema so app.openapi() recomputes.
    app.openapi_schema = None
    second = app.openapi()
    assert first == second, "OpenAPI schema is non-deterministic across calls"
