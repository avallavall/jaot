"""Anti-oracle 404 helper for cross-tenant IDOR tests (Pattern 3 Path B).

Two assertions are exposed:

    - ``assert_cross_tenant_404_anti_oracle``       — READ variant (GET)
    - ``assert_cross_tenant_404_anti_oracle_write`` — WRITE variant
      (PATCH / PUT / DELETE)

Both perform two requests against the same endpoint template:

    1. ``endpoint_template.format(id=cross_tenant_resource_id)`` — a
       resource that EXISTS in another organisation.
    2. ``endpoint_template.format(id=nonexistent_id)`` — an id that does
       NOT exist anywhere.

The invariant is that BOTH return HTTP 404 with a BYTE-IDENTICAL
``detail`` field. Any divergence is an oracle leaking the
"exists-elsewhere" vs. "does-not-exist" distinction (OWASP A01 IDOR).

Why a helper module (D-09 Path B)
---------------------------------

This approach deliberately keeps the production code (``app/``) untouched.
The alternative (Path A) would have extracted a ``NOT_FOUND_DETAIL``
constant into ``app/`` and tests would compare against it. Path B keeps
the invariant test-side: the helper fetches BOTH detail strings
dynamically per-call and compares them — never against a hardcoded
baseline. This eliminates Pitfall 4 (false-positive "anti-oracle" tests
that compare against a typo).

References
----------

    - tests/test_tenant_isolation.py (CR-02, lines 266-385) — canonical
      anti-oracle template; this helper extracts that shape for reuse.
"""

from __future__ import annotations

from typing import Any

_WRITE_METHODS: tuple[str, ...] = ("post", "patch", "put", "delete")


def _default_nonexistent_id(cross_tenant_resource_id: str) -> str:
    """Derive a nonexistent id from a real-looking id.

    The convention is ``<prefix>_does_not_exist_anywhere`` where
    ``prefix`` is the first underscore-segment of ``cross_tenant_resource_id``
    (e.g. ``"bld_abc"`` -> ``"bld_does_not_exist_anywhere"``).

    For ids without an underscore separator (very rare; legacy raw
    UUIDs), the full id is used as the prefix.
    """
    head, sep, _tail = cross_tenant_resource_id.partition("_")
    prefix = head if sep else cross_tenant_resource_id
    return f"{prefix}_does_not_exist_anywhere"


def assert_cross_tenant_404_anti_oracle(
    client_as_other_org: Any,
    endpoint_template: str,
    cross_tenant_resource_id: str,
    nonexistent_id: str | None = None,
) -> None:
    """Anti-oracle 404 assertion for GET (SC4 + TH-01 invariant).

    Issues two GET requests against ``endpoint_template``:

        1. with ``cross_tenant_resource_id`` (resource exists in another org)
        2. with ``nonexistent_id`` (resource does not exist anywhere)

    Asserts BOTH return 404 AND the ``detail`` field of the JSON body is
    byte-identical. Any divergence is an information-disclosure oracle.

    Args:
        client_as_other_org: A TestClient / authenticated client already
            authenticated as a user from the *other* organisation.
        endpoint_template: The URL template containing a single ``{id}``
            placeholder (e.g. ``"/api/v2/builder/{id}"``).
        cross_tenant_resource_id: The id of a resource owned by another
            org. The request is expected to 404 because the caller's org
            does not own it.
        nonexistent_id: An id that does not exist anywhere. Defaults to
            the value returned by ``_default_nonexistent_id``.

    Raises:
        AssertionError: If either response is not 404, or if the two
            detail strings differ.
    """
    if nonexistent_id is None:
        nonexistent_id = _default_nonexistent_id(cross_tenant_resource_id)

    cross_path = endpoint_template.format(id=cross_tenant_resource_id)
    nonex_path = endpoint_template.format(id=nonexistent_id)

    cross_resp = client_as_other_org.get(cross_path)
    nonex_resp = client_as_other_org.get(nonex_path)

    assert cross_resp.status_code == 404, (
        f"cross-tenant GET {cross_path} must 404, got {cross_resp.status_code}: {cross_resp.text}"
    )
    assert nonex_resp.status_code == 404, (
        f"nonexistent GET {nonex_path} must 404, got {nonex_resp.status_code}: {nonex_resp.text}"
    )

    cross_detail = cross_resp.json().get("detail")
    nonex_detail = nonex_resp.json().get("detail")
    assert cross_detail == nonex_detail, (
        f"Anti-oracle violation on GET {endpoint_template}: "
        f"cross-tenant detail={cross_detail!r} != nonexistent detail={nonex_detail!r}"
    )


def assert_cross_tenant_404_anti_oracle_write(
    client_as_other_org: Any,
    method: str,
    endpoint_template: str,
    cross_tenant_resource_id: str,
    body: dict[str, Any] | None = None,
    nonexistent_id: str | None = None,
) -> None:
    """Anti-oracle 404 assertion for write methods (POST / PATCH / PUT / DELETE).

    Same invariant as the GET variant. ``method`` must be one of
    ``post``, ``patch``, ``put``, ``delete`` (case-insensitive). ``body`` is
    forwarded as ``json=body`` for POST / PATCH / PUT; ignored for DELETE.

    Raises:
        AssertionError: If either response is not 404, or if the detail
            strings differ.
        ValueError: If ``method`` is not one of the supported write
            methods.
    """
    method_normalised = method.lower()
    if method_normalised not in _WRITE_METHODS:
        raise ValueError(f"method must be one of {_WRITE_METHODS!r}, got {method!r}")

    if nonexistent_id is None:
        nonexistent_id = _default_nonexistent_id(cross_tenant_resource_id)

    cross_path = endpoint_template.format(id=cross_tenant_resource_id)
    nonex_path = endpoint_template.format(id=nonexistent_id)

    request_fn = getattr(client_as_other_org, method_normalised)
    kwargs: dict[str, Any] = {}
    if method_normalised in ("post", "patch", "put") and body is not None:
        kwargs["json"] = body

    cross_resp = request_fn(cross_path, **kwargs)
    nonex_resp = request_fn(nonex_path, **kwargs)

    assert cross_resp.status_code == 404, (
        f"cross-tenant {method_normalised.upper()} {cross_path} must 404, "
        f"got {cross_resp.status_code}: {cross_resp.text}"
    )
    assert nonex_resp.status_code == 404, (
        f"nonexistent {method_normalised.upper()} {nonex_path} must 404, "
        f"got {nonex_resp.status_code}: {nonex_resp.text}"
    )

    cross_detail = cross_resp.json().get("detail")
    nonex_detail = nonex_resp.json().get("detail")
    assert cross_detail == nonex_detail, (
        f"Anti-oracle violation on {method_normalised.upper()} {endpoint_template}: "
        f"cross-tenant detail={cross_detail!r} != nonexistent detail={nonex_detail!r}"
    )
