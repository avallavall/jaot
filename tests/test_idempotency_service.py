"""Characterization tests for app/services/idempotency.py.

Pure-function tests — no DB, no mocks, no authenticated_client needed.
These pin the exact digest format (org_id:key:body order, exe_ik_ prefix,
24-hex truncation) as a financial-safety invariant.
"""

from __future__ import annotations

import hashlib

from app.services.idempotency import idempotency_execution_id


class TestIdempotencyExecutionId:
    """Characterization tests for idempotency_execution_id().

    The output format is a financial-safety invariant: a change to the input
    order or prefix would cause cached-result lookups to miss on retries,
    silently charging credits twice on every duplicate solve request.
    """

    def test_returns_string_with_exe_ik_prefix(self) -> None:
        result = idempotency_execution_id("key-abc", "org_123", '{"x":1}')
        assert result.startswith("exe_ik_")

    def test_total_length_is_31(self) -> None:
        """exe_ik_ (7) + 24 hex chars = 31."""
        result = idempotency_execution_id("key-abc", "org_123", '{"x":1}')
        assert len(result) == 31

    def test_hex_suffix_only_contains_hex_chars(self) -> None:
        result = idempotency_execution_id("key-abc", "org_123", '{"x":1}')
        suffix = result[len("exe_ik_") :]
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_deterministic_same_inputs(self) -> None:
        r1 = idempotency_execution_id("k1", "org_1", "b1")
        r2 = idempotency_execution_id("k1", "org_1", "b1")
        assert r1 == r2

    def test_different_org_different_output(self) -> None:
        """org binding: two orgs with the same key+body must not collide."""
        r1 = idempotency_execution_id("same-key", "org_A", "same-body")
        r2 = idempotency_execution_id("same-key", "org_B", "same-body")
        assert r1 != r2

    def test_different_body_different_output(self) -> None:
        """body binding: same key+org with different body yields a different id."""
        r1 = idempotency_execution_id("same-key", "org_1", '{"x":1}')
        r2 = idempotency_execution_id("same-key", "org_1", '{"x":2}')
        assert r1 != r2

    def test_different_key_different_output(self) -> None:
        r1 = idempotency_execution_id("key-1", "org_1", "body")
        r2 = idempotency_execution_id("key-2", "org_1", "body")
        assert r1 != r2

    # CONTRACT-TEST: idempotency-execution-id-format
    #   The digest format string is "{org_id}:{idempotency_key}:{body_canonical}".
    #   The prefix is "exe_ik_" and only the first 24 hex chars of the SHA-256
    #   digest are used.  Mutating the input order or prefix causes a double-charge
    #   regression (a solved request is no longer found in the idempotency cache).
    #   Removing or weakening this test removes the only commit-time guard against
    #   that financial-safety regression.
    def test_golden_value_byte_identical_to_sha256(self) -> None:
        """Pins the exact format: sha256("{org_id}:{key}:{body}")[:24] with exe_ik_ prefix."""
        key = "k1"
        org_id = "org_1"
        body = "b1"
        expected_digest = hashlib.sha256(f"{org_id}:{key}:{body}".encode()).hexdigest()[:24]
        expected = f"exe_ik_{expected_digest}"
        assert idempotency_execution_id(key, org_id, body) == expected
