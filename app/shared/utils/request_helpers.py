"""HTTP request utility helpers."""

import ipaddress

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
_CLIENT_IP_HEADERS = (b"x-real-ip", b"cf-connecting-ip", b"x-forwarded-for")


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

    Security rests on a deployment invariant that holds for the shipped Compose
    topology and must hold for any self-host:

      1. The backend publishes no host ports — it is reachable only on the
         internal Docker network (verified: only Caddy publishes 80/443).
      2. The edge proxy (Caddy) is the sole public ingress and its
         ``reverse_proxy`` always appends ``X-Forwarded-For``.

    Therefore a request that carries NO forwarding header (any of
    ``_CLIENT_IP_HEADERS``) AND comes from a private/loopback address cannot be an
    external client — it is internal traffic such as the frontend's SSR fetches
    or container health checks. An external client always arrives through Caddy
    with a forwarding header set, and cannot strip it; forging a *fake* one only
    keeps it on the external (rate-limited) path, never the internal one.

    Used to exempt SSR traffic from the anonymous per-IP public rate limit (all
    server-side renders egress from a single container IP, so without this they
    would share one 60/min bucket across every visitor: a burst → 429 → SSR 500),
    and to keep our own infrastructure out of the marketplace's visit telemetry.
    """
    has_forward_header = any(name in _CLIENT_IP_HEADERS for name, _ in scope.get("headers", []))
    if has_forward_header:
        return False
    client = scope.get("client")
    if not client:
        return False
    return _is_private_or_loopback(client[0])


def _first_hop(value: str) -> str:
    """First entry of a comma-separated forwarding header."""
    return value.split(",")[0].strip()


def get_client_ip(request: Request) -> str:
    """The caller's address, from the most trustworthy header that is present.

    ``request.client.host`` is not consulted before the headers, and not because
    of the classic "behind a proxy it returns the proxy's IP": uvicorn runs with
    ``proxy_headers=True``, so it has already rewritten ``request.client`` from
    ``X-Forwarded-For`` — taking that header's *first* entry, which is the entry a
    caller chooses. Trusting it let a request assert its own address: verified in
    production, one call carrying ``X-Forwarded-For: 8.8.8.8`` was recorded as US
    and opened its own ``rl:public_ip:8.8.8.8`` rate-limit bucket, which is a way
    around every per-IP limit including the one on login attempts.
    """
    for header in _CLIENT_IP_HEADERS:
        value = request.headers.get(header.decode())
        if value and value.strip():
            return _first_hop(value)
    return request.client.host if request.client else "unknown"


def get_client_ip_from_scope(scope: dict) -> str:
    """Same precedence as :func:`get_client_ip`, for pure ASGI middleware.

    Used by the anonymous per-IP rate limit, which runs before a Request object
    exists. Header order in the scope is irrelevant: the loop below is driven by
    the trust order, not by the order the headers happen to arrive in — the
    previous implementation returned whichever came first, so a caller could put
    ``X-Forwarded-For`` ahead of the header a proxy had set.
    """
    headers = scope.get("headers", [])
    for wanted in _CLIENT_IP_HEADERS:
        for header_name, header_value in headers:
            if header_name == wanted:
                decoded = header_value.decode().strip()
                if decoded:
                    return _first_hop(decoded)
    client = scope.get("client")
    if client:
        return client[0]
    return "unknown"
