"""Unit tests for trusted-internal-request detection (rate-limit exemption).

The exemption's whole job is to tell SSR/service-to-service traffic apart from
external clients. These cases pin the decision boundary; the security argument
(why "no proxy header + private IP" cannot be forged externally) lives in the
is_trusted_internal_request docstring.
"""

from __future__ import annotations

from app.shared.utils.request_helpers import (
    _is_private_or_loopback,
    is_trusted_internal_request,
)


def _scope(headers: list[tuple[bytes, bytes]] | None = None, client: tuple | None = None) -> dict:
    return {"headers": headers or [], "client": client}


class TestIsPrivateOrLoopback:
    def test_rfc1918_ranges(self) -> None:
        assert _is_private_or_loopback("10.0.0.1")
        assert _is_private_or_loopback("172.18.0.5")  # default Docker bridge range
        assert _is_private_or_loopback("192.168.1.10")

    def test_loopback_and_link_local(self) -> None:
        assert _is_private_or_loopback("127.0.0.1")
        assert _is_private_or_loopback("169.254.1.1")
        assert _is_private_or_loopback("::1")

    def test_public_addresses_are_not_private(self) -> None:
        # Genuinely global addresses. (Note: RFC-5737 doc ranges like
        # 203.0.113.0/24 are is_private=True in Python 3.12 — fine here, they
        # never appear as a real client IP; XFF is the actual trust gate.)
        assert not _is_private_or_loopback("8.8.8.8")
        assert not _is_private_or_loopback("1.1.1.1")

    def test_garbage_is_not_private(self) -> None:
        assert not _is_private_or_loopback("testclient")
        assert not _is_private_or_loopback("")
        assert not _is_private_or_loopback("not-an-ip")


class TestIsTrustedInternalRequest:
    def test_private_ip_no_proxy_header_is_internal(self) -> None:
        # The frontend SSR fetch: direct on the Docker network, no XFF.
        assert is_trusted_internal_request(_scope(client=("172.18.0.5", 4321)))

    def test_loopback_no_proxy_header_is_internal(self) -> None:
        # Container health checks (wget 127.0.0.1).
        assert is_trusted_internal_request(_scope(client=("127.0.0.1", 5000)))

    def test_public_ip_no_proxy_header_is_not_internal(self) -> None:
        # Shouldn't happen in the shipped topology, but if a public IP reaches
        # the backend directly it must NOT be treated as trusted.
        assert not is_trusted_internal_request(_scope(client=("8.8.8.8", 5000)))

    def test_x_forwarded_for_means_external_even_from_private_ip(self) -> None:
        # Came through Caddy (which always appends XFF) → external client, even
        # though the immediate peer (Caddy) is on a private IP.
        scope = _scope(
            headers=[(b"x-forwarded-for", b"203.0.113.5")],
            client=("172.18.0.2", 1234),
        )
        assert not is_trusted_internal_request(scope)

    def test_x_real_ip_means_external(self) -> None:
        scope = _scope(
            headers=[(b"x-real-ip", b"203.0.113.5")],
            client=("172.18.0.2", 1234),
        )
        assert not is_trusted_internal_request(scope)

    def test_forged_xff_keeps_request_external(self) -> None:
        # An attacker adding a fake XFF only keeps itself on the rate-limited
        # path — it can never use XFF to reach the internal branch.
        scope = _scope(
            headers=[(b"x-forwarded-for", b"10.0.0.1")],
            client=("8.8.8.8", 1234),
        )
        assert not is_trusted_internal_request(scope)

    def test_missing_client_is_not_internal(self) -> None:
        assert not is_trusted_internal_request(_scope(client=None))

    def test_header_match_is_case_insensitive_bytes(self) -> None:
        # ASGI header names are always lowercased bytes; confirm we match them.
        scope = _scope(
            headers=[(b"x-forwarded-for", b"203.0.113.9")],
            client=("172.18.0.2", 1234),
        )
        assert not is_trusted_internal_request(scope)
