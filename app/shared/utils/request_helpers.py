"""HTTP request utility helpers."""

import ipaddress

from starlette.requests import Request


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

    Therefore a request that carries NO forwarding header (``X-Forwarded-For`` /
    ``X-Real-IP``) AND comes from a private/loopback address cannot be an
    external client — it is internal traffic such as the frontend's SSR fetches
    or container health checks. An external client always arrives through Caddy
    with an ``X-Forwarded-For`` set, and cannot strip it; forging a *fake* XFF
    only keeps it on the external (rate-limited) path, never the internal one.

    Used to exempt SSR traffic from the anonymous per-IP public rate limit: all
    server-side renders egress from a single container IP, so without this they
    would share one 60/min bucket across every visitor (a burst → 429 → SSR 500).
    """
    has_forward_header = any(
        name in (b"x-forwarded-for", b"x-real-ip") for name, _ in scope.get("headers", [])
    )
    if has_forward_header:
        return False
    client = scope.get("client")
    if not client:
        return False
    return _is_private_or_loopback(client[0])


def get_client_ip(request: Request) -> str:
    """Extract real client IP, respecting X-Forwarded-For and X-Real-IP headers.

    When behind a reverse proxy (e.g., Caddy), request.client.host returns the
    proxy's IP. This function checks proxy headers first.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def get_client_ip_from_scope(scope: dict) -> str:
    """Extract real client IP from ASGI scope headers.

    Used in pure ASGI middleware where a Request object is not yet available.
    """
    for header_name, header_value in scope.get("headers", []):
        if header_name == b"x-forwarded-for":
            return header_value.decode().split(",")[0].strip()
        if header_name == b"x-real-ip":
            return header_value.decode().strip()
    client = scope.get("client")
    if client:
        return client[0]
    return "unknown"
