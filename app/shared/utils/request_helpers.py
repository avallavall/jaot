"""HTTP request utility helpers."""

import ipaddress
from collections.abc import Mapping

from starlette.requests import Request

#: Headers that identify the caller, most trustworthy first. A header is only
#: trustworthy when a proxy we control *overwrites* it on every request — a
#: header the client can set and the chain merely forwards is a client-chosen
#: value, whatever its name.
#:
#: 1. ``X-Real-IP`` — Caddy sets it from its own resolved ``client_ip``
#:    (``header_up X-Real-IP {http.request.client_ip}``), replacing anything the
#:    caller sent. This is the one to trust in the shipped topology.
#: 2. ``CF-Connecting-IP`` — Cloudflare overwrites it at its edge, so it survives
#:    a deployment where Caddy has not been reloaded with the directive above.
#: 3. ``X-Forwarded-For`` — kept last and deliberately so: proxies *append* to
#:    it, so the first entry is whatever the caller put there. It is a fallback
#:    for a self-host fronted by neither of the above, not a source of truth.
_CLIENT_IP_HEADER_NAMES = ("x-real-ip", "cf-connecting-ip", "x-forwarded-for")
#: Same list, pre-encoded: the ASGI scope carries header names as bytes, and this
#: runs on the anonymous rate-limit path for every public request.
_CLIENT_IP_HEADERS = tuple(name.encode() for name in _CLIENT_IP_HEADER_NAMES)


def _is_private_or_loopback(ip: str) -> bool:
    """True for RFC-1918 / loopback / link-local addresses (Docker-internal traffic)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def is_trusted_internal_request(scope: dict) -> bool:
    """True when a request originates from inside the cluster (service-to-service)
    rather than from an external client via the edge proxy.

    A request that carries NO forwarding header (any of ``_CLIENT_IP_HEADERS``)
    AND comes from a private/loopback address did not arrive through the edge
    proxy, whose ``reverse_proxy`` always appends ``X-Forwarded-For``. It is
    internal traffic: a server-side render, a container health check.

    Used to exempt those from the anonymous per-IP public rate limit — every SSR
    egresses from one container address, so without the exemption they share a
    single 60/min bucket across all visitors and a burst turns into 429 → SSR 500.

    ⚠️ **This is not a security boundary, and must not be used as one.** The
    invariant it would need — "nothing but the edge proxy can reach the API from a
    private address" — does not hold for the shipped composes:

      * ``deploy/docker-compose.home.yml`` publishes the frontend on ``3000:3000``
        (all interfaces), and ``next.config.ts`` rewrites ``/api/*`` to the API
        without adding any forwarding header. Any host on the LAN can therefore
        reach every public endpoint through that port and land on this exemption.
      * ``docker-compose.yml`` publishes the API itself on ``127.0.0.1:8001``.

    So treat it as "traffic that should not be rate-limited as if it were one
    visitor", not as "trusted". Anything that must not be forgeable — telemetry
    the marketplace bills nobody for, but an author reads — asks the caller to
    declare itself instead (``_is_own_traffic`` in the catalog routes).
    """
    has_forward_header = any(name in _CLIENT_IP_HEADERS for name, _ in scope.get("headers", []))
    if has_forward_header:
        return False
    client = scope.get("client")
    if not client:
        return False
    return _is_private_or_loopback(client[0])


def _parse_hop(value: str) -> str | None:
    """The first entry of a forwarding header, if it parses as an address.

    Rejecting what does not parse is not tidiness. These values are persisted —
    ``ContactMessage.ip_address`` is ``String(64)``, so a longer one raises
    ``StringDataRightTruncation`` at commit, an unhandled 500 on a public
    endpoint — and they are used as Redis keys, so accepting arbitrary text hands
    a caller an unbounded key space. A header that does not carry an address is
    treated as absent, and the next one gets its turn.
    """
    first = value.split(",")[0].strip()
    if not first:
        return None
    try:
        ipaddress.ip_address(first)
    except ValueError:
        return None
    return first


def get_client_ip_from_headers(headers: Mapping[str, str]) -> str | None:
    """The caller's address from a plain header mapping, or ``None``.

    Third entry point because the MCP layer holds a dict rather than a Request or
    an ASGI scope — and it had grown its own copy of the defect this module
    exists to prevent (first hop of ``X-Forwarded-For``, no questions asked).
    """
    for header in _CLIENT_IP_HEADER_NAMES:
        value = headers.get(header)
        if value:
            parsed = _parse_hop(value)
            if parsed:
                return parsed
    return None


def get_client_ip(request: Request) -> str:
    """The caller's address, from the most trustworthy header that carries one.

    ``request.client.host`` is not consulted before the headers, and not because
    of the classic "behind a proxy it returns the proxy's IP": uvicorn runs with
    ``proxy_headers=True``, so it has already rewritten ``request.client`` from
    ``X-Forwarded-For`` — taking that header's *first* entry, which is the entry a
    caller chooses. Trusting it let a request assert its own address: verified in
    production, one call carrying ``X-Forwarded-For: 8.8.8.8`` was recorded as US
    and opened its own ``rl:public_ip:8.8.8.8`` rate-limit bucket, which is a way
    around every per-IP limit including the one on login attempts.
    """
    from_headers = get_client_ip_from_headers(request.headers)
    if from_headers:
        return from_headers
    return request.client.host if request.client else "unknown"


def get_client_ip_from_scope(scope: dict) -> str:
    """Same precedence as :func:`get_client_ip`, for pure ASGI middleware.

    Used by the anonymous per-IP rate limit, which runs before a Request object
    exists. Header order on the wire is irrelevant: the best-ranked header wins,
    where the previous implementation returned whichever arrived first — so a
    caller could simply put ``X-Forwarded-For`` ahead of the one a proxy had set.
    """
    best: tuple[int, str] | None = None
    for header_name, header_value in scope.get("headers", []):
        try:
            rank = _CLIENT_IP_HEADERS.index(header_name)
        except ValueError:
            continue
        if best is not None and rank >= best[0]:
            continue
        parsed = _parse_hop(header_value.decode())
        if parsed:
            best = (rank, parsed)
    if best is not None:
        return best[1]
    client = scope.get("client")
    if client:
        return client[0]
    return "unknown"
