"""Unit tests for ``tests/_helpers/anti_oracle.py``.

These tests do not touch the database or the FastAPI app. They stub the
HTTP client with ``unittest.mock.MagicMock`` (no ``spec=Session``, so the
Tier-1 anti-pattern hook stays green) and verify the helper's PASS / FAIL
paths.

References
----------

- scripts/check_test_quality_tier1.py — confirms MagicMock(...) without
  ``spec=Session`` is allowed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests._helpers.anti_oracle import (
    _default_nonexistent_id,
    assert_cross_tenant_404_anti_oracle,
    assert_cross_tenant_404_anti_oracle_write,
)


def _stub_response(status_code: int, detail: str | None = None) -> MagicMock:
    """Build a stub HTTP response with ``status_code`` and a ``detail`` JSON body."""
    response = MagicMock()
    response.status_code = status_code
    payload: dict[str, str] = {} if detail is None else {"detail": detail}
    response.json = MagicMock(return_value=payload)
    response.text = f"<stub {status_code}>"
    return response


# ---------------------------------------------------------------------------
# READ variant — assert_cross_tenant_404_anti_oracle
# ---------------------------------------------------------------------------


def test_pass_identical_404_details():
    """PASS path: both responses 404 with byte-identical detail."""
    detail = "Builder document not found"
    client = MagicMock()
    client.get = MagicMock(
        side_effect=[
            _stub_response(404, detail),
            _stub_response(404, detail),
        ]
    )

    # Must not raise
    assert_cross_tenant_404_anti_oracle(
        client,
        endpoint_template="/api/v2/builder/{id}",
        cross_tenant_resource_id="bld_real_in_other_org",
        nonexistent_id="bld_does_not_exist_anywhere",
    )

    assert client.get.call_count == 2
    paths = [call.args[0] for call in client.get.call_args_list]
    assert paths == [
        "/api/v2/builder/bld_real_in_other_org",
        "/api/v2/builder/bld_does_not_exist_anywhere",
    ]


def test_fail_cross_tenant_not_404():
    """FAIL: cross-tenant request returns 403 (would leak existence)."""
    client = MagicMock()
    client.get = MagicMock(
        side_effect=[
            _stub_response(403, "Forbidden"),
            _stub_response(404, "Not found"),
        ]
    )

    with pytest.raises(AssertionError, match="cross-tenant GET .* must 404"):
        assert_cross_tenant_404_anti_oracle(
            client,
            endpoint_template="/api/v2/builder/{id}",
            cross_tenant_resource_id="bld_real_in_other_org",
            nonexistent_id="bld_does_not_exist_anywhere",
        )


def test_fail_nonexistent_not_404():
    """FAIL: nonexistent request returns 200 (impossible-but-protective branch)."""
    detail = "Builder document not found"
    client = MagicMock()
    client.get = MagicMock(
        side_effect=[
            _stub_response(404, detail),
            _stub_response(200, None),
        ]
    )

    with pytest.raises(AssertionError, match="nonexistent GET .* must 404"):
        assert_cross_tenant_404_anti_oracle(
            client,
            endpoint_template="/api/v2/builder/{id}",
            cross_tenant_resource_id="bld_real_in_other_org",
            nonexistent_id="bld_does_not_exist_anywhere",
        )


def test_fail_details_differ():
    """FAIL: both 404 but the detail strings reveal cross-tenant existence."""
    client = MagicMock()
    client.get = MagicMock(
        side_effect=[
            _stub_response(404, "Builder document not found in this org"),
            _stub_response(404, "Builder document not found"),
        ]
    )

    with pytest.raises(AssertionError, match="Anti-oracle violation"):
        assert_cross_tenant_404_anti_oracle(
            client,
            endpoint_template="/api/v2/builder/{id}",
            cross_tenant_resource_id="bld_real_in_other_org",
            nonexistent_id="bld_does_not_exist_anywhere",
        )


def test_default_nonexistent_id_derivation():
    """PASS: when ``nonexistent_id`` is None, the prefix-based default is used."""
    detail = "Workspace not found"
    client = MagicMock()
    client.get = MagicMock(
        side_effect=[
            _stub_response(404, detail),
            _stub_response(404, detail),
        ]
    )

    assert_cross_tenant_404_anti_oracle(
        client,
        endpoint_template="/api/v2/workspaces/{id}",
        cross_tenant_resource_id="wks_abcdef123",
        # nonexistent_id intentionally omitted
    )

    paths = [call.args[0] for call in client.get.call_args_list]
    assert paths == [
        "/api/v2/workspaces/wks_abcdef123",
        "/api/v2/workspaces/wks_does_not_exist_anywhere",
    ]


def test_default_derivation_helper_no_underscore():
    """Edge: id without underscore — full id becomes the prefix."""
    assert _default_nonexistent_id("rawid") == "rawid_does_not_exist_anywhere"


def test_default_derivation_helper_prefixed():
    """Edge: id with underscore — first segment is the prefix."""
    assert _default_nonexistent_id("inv_abc123") == "inv_does_not_exist_anywhere"


# ---------------------------------------------------------------------------
# WRITE variant — assert_cross_tenant_404_anti_oracle_write
# ---------------------------------------------------------------------------


def test_write_variant_patch_pass():
    """PASS path for PATCH: both 404 with identical detail; body forwarded."""
    detail = "Workspace not found"
    client = MagicMock()
    client.patch = MagicMock(
        side_effect=[
            _stub_response(404, detail),
            _stub_response(404, detail),
        ]
    )

    assert_cross_tenant_404_anti_oracle_write(
        client,
        method="PATCH",
        endpoint_template="/api/v2/workspaces/{id}",
        cross_tenant_resource_id="wks_other_org",
        body={"name": "Hacked"},
        nonexistent_id="wks_does_not_exist_anywhere",
    )

    # Both requests forwarded the body
    for call in client.patch.call_args_list:
        assert call.kwargs == {"json": {"name": "Hacked"}}


def test_write_variant_delete_pass():
    """PASS path for DELETE: both 404 with identical detail; no body forwarded."""
    detail = "Invite not found"
    client = MagicMock()
    client.delete = MagicMock(
        side_effect=[
            _stub_response(404, detail),
            _stub_response(404, detail),
        ]
    )

    assert_cross_tenant_404_anti_oracle_write(
        client,
        method="delete",
        endpoint_template="/api/v2/workspaces/wks_x/invites/{id}",
        cross_tenant_resource_id="inv_other_org",
    )

    # DELETE never gets a body forwarded
    for call in client.delete.call_args_list:
        assert call.kwargs == {}


def test_write_variant_rejects_unknown_method():
    """FAIL: only PATCH / PUT / DELETE are allowed."""
    client = MagicMock()
    with pytest.raises(ValueError, match="method must be one of"):
        assert_cross_tenant_404_anti_oracle_write(
            client,
            method="get",  # not a write method
            endpoint_template="/api/v2/builder/{id}",
            cross_tenant_resource_id="bld_x",
        )


def test_write_variant_fail_details_differ():
    """FAIL: PATCH responses differ in detail string (anti-oracle violation)."""
    client = MagicMock()
    client.patch = MagicMock(
        side_effect=[
            _stub_response(404, "Workspace not found in this org"),
            _stub_response(404, "Workspace not found"),
        ]
    )

    with pytest.raises(AssertionError, match="Anti-oracle violation on PATCH"):
        assert_cross_tenant_404_anti_oracle_write(
            client,
            method="patch",
            endpoint_template="/api/v2/workspaces/{id}",
            cross_tenant_resource_id="wks_other_org",
            body={"name": "Renamed"},
        )
