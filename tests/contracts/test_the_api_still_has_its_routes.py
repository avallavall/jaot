"""The API publishes the whole surface, not a fraction of it.

`fastapi<0.137.0` was pinned for two years because `len(app.routes)` fell from
248 to 8 on a newer version and that was read as 228 routes going missing. It
was not: 0.137 changed `include_router` to store a lazy include record instead
of copying the child router's routes, so the list stopped being a count. The
app served the same 194 paths and 238 operations throughout.

Removing that ceiling removed the only thing standing between a bad FastAPI
release and a deploy, so the guard has to be replaced by one that measures what
the pin was trying to protect. This is it. It asks the app what it publishes,
which is the question the route list was standing in for, and it is the only
check in the suite that would notice a composition failure.

The floor is deliberately a floor and not an exact number: adding an endpoint
must not turn this test red, losing a router must.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.contract

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})

#: Counted 2026-08-26 at 194 paths / 238 operations. The floors sit just under
#: that, close enough that a single dropped sub-router (the smallest is 1 route,
#: the largest 37) is caught, and far enough that ordinary growth is not.
_MIN_PATHS = 185
_MIN_OPERATIONS = 225

#: One representative path per top-level router, so a failure names the router
#: that went missing instead of only a number. A prefix is enough: these exist
#: to prove the router was composed in, not to pin any single endpoint's shape.
_A_PATH_FROM_EVERY_ROUTER = [
    "/api/v2/models/catalog",
    "/api/v2/solve",
    "/api/v2/solvers/available",
    "/api/v2/solve/templates",
    "/api/v2/keys",
    "/api/v2/auth/login",
    "/api/v2/health",
    "/api/v2/notifications",
    "/api/v2/projects",
    "/api/v2/triggers",
    "/api/v2/llm/conversations",
    "/api/v2/workspaces",
    "/api/v2/user/data-export",
    "/api/v2/contact",
]


# CONTRACT-TEST: the composed app publishes its whole route surface.
def test_the_openapi_schema_is_not_a_skeleton(app) -> None:
    spec = app.openapi()
    paths = spec.get("paths", {})
    operations = sum(len([m for m in methods if m in _HTTP_METHODS]) for methods in paths.values())

    assert len(paths) >= _MIN_PATHS, (
        f"the API publishes {len(paths)} paths, under the floor of {_MIN_PATHS} — "
        "a router was probably composed in without its routes"
    )
    assert operations >= _MIN_OPERATIONS, (
        f"the API publishes {operations} operations, under the floor of {_MIN_OPERATIONS}"
    )


# CONTRACT-TEST: every top-level router reached the schema.
def test_every_router_contributed_at_least_one_path(app) -> None:
    published = set(app.openapi().get("paths", {}))
    missing = [
        probe
        for probe in _A_PATH_FROM_EVERY_ROUTER
        if not any(p.startswith(probe) for p in published)
    ]

    assert not missing, f"these routers published nothing: {missing}"
