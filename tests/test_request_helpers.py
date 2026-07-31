"""Who the server believes the caller is.

Every per-IP limit in the platform is keyed on this — the anonymous 60/min, the
login-attempt limiter, signup, the contact form — plus the `ip_address` written
to the audit log. Before this was fixed, all of them read the FIRST entry of
`X-Forwarded-For`, which is the entry a caller puts there: proxies append.

Verified against production before fixing: one request carrying
`X-Forwarded-For: 8.8.8.8` was stored as country US and opened its own
`rl:public_ip:8.8.8.8` buckets in Redis, i.e. a caller could hand itself a fresh
rate-limit allowance per invented address, login attempts included.

The tests are written against the trust order rather than any single header, so
they keep holding if a deployment terminates somewhere else.
"""

from starlette.requests import Request

from app.shared.utils.request_helpers import (
    get_client_ip,
    get_client_ip_from_scope,
    is_trusted_internal_request,
)

REAL = "88.12.34.56"
FORGED = "8.8.8.8"


def _scope(headers: dict[str, str], client: tuple[str, int] | None = ("172.18.0.5", 40000)) -> dict:
    return {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/api/v2/models/catalog",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    }


def _request(headers: dict[str, str], client: tuple[str, int] | None = ("172.18.0.5", 40000)):
    return Request(_scope(headers, client))


class TestForgedForwardingHeaders:
    """A caller must not be able to choose the address it is limited by."""

    # CONTRACT-TEST: X-Real-IP (set by our own proxy) outranks a forged XFF
    def test_the_proxys_header_wins_over_a_forged_first_hop(self):
        headers = {"X-Real-IP": REAL, "X-Forwarded-For": f"{FORGED}, {REAL}"}
        assert get_client_ip(_request(headers)) == REAL
        assert get_client_ip_from_scope(_scope(headers)) == REAL

    # CONTRACT-TEST: Cloudflare's header outranks a forged XFF
    def test_cloudflares_header_wins_when_the_proxy_header_is_absent(self):
        """Cloudflare discards any CF-Connecting-IP the client supplies, so it is
        trustworthy even before Caddy has been reloaded with the header_up rule."""
        headers = {"CF-Connecting-IP": REAL, "X-Forwarded-For": f"{FORGED}, {REAL}"}
        assert get_client_ip(_request(headers)) == REAL
        assert get_client_ip_from_scope(_scope(headers)) == REAL

    def test_header_order_on_the_wire_does_not_decide(self):
        """The scope reader used to return whichever header came first, so a
        caller could simply send X-Forwarded-For ahead of the trusted one."""
        scope = _scope({})
        scope["headers"] = [
            (b"x-forwarded-for", f"{FORGED}, {REAL}".encode()),
            (b"x-real-ip", REAL.encode()),
        ]
        assert get_client_ip_from_scope(scope) == REAL

    def test_forwarded_for_is_still_used_when_it_is_all_there_is(self):
        """A self-host behind neither Caddy nor Cloudflare has nothing better.
        This is a fallback, and the docstring says as much."""
        headers = {"X-Forwarded-For": f"{REAL}, 172.70.100.1"}
        assert get_client_ip(_request(headers)) == REAL

    def test_an_empty_header_does_not_shadow_a_real_one(self):
        """A blank X-Real-IP must not win and return "" — a proxy that sets the
        header but resolves nothing would otherwise blank out every bucket key,
        putting every caller in one shared limit."""
        headers = {"X-Real-IP": "  ", "CF-Connecting-IP": REAL}
        assert get_client_ip(_request(headers)) == REAL
        assert get_client_ip_from_scope(_scope(headers)) == REAL

    def test_the_socket_is_the_last_resort(self):
        assert get_client_ip(_request({}, client=("10.1.2.3", 5))) == "10.1.2.3"
        assert get_client_ip(_request({}, client=None)) == "unknown"
        assert get_client_ip_from_scope(_scope({}, client=None)) == "unknown"


class TestInternalRequestDetection:
    """The same header list decides what counts as our own traffic."""

    def test_a_private_caller_with_no_forwarding_header_is_internal(self):
        assert is_trusted_internal_request(_scope({})) is True

    def test_any_forwarding_header_puts_the_caller_outside(self):
        """Including Cloudflare's, which the previous list did not mention — a
        request carrying only CF-Connecting-IP would have been read as internal
        and skipped both the rate limit and the visit telemetry."""
        for header in ("X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP"):
            assert is_trusted_internal_request(_scope({header: REAL})) is False, header

    def test_a_public_caller_is_never_internal(self):
        assert is_trusted_internal_request(_scope({}, client=(REAL, 40000))) is False

    def test_no_client_is_not_internal(self):
        assert is_trusted_internal_request(_scope({}, client=None)) is False
