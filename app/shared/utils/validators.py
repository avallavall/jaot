"""Common validation utilities."""

import ipaddress
import logging
import socket
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# DNS resolution cache: hostname -> (ip_list, expires_at_monotonic)
_DNS_CACHE: dict[str, tuple[list[str], float]] = {}
_DNS_TTL = 60.0  # seconds


def _resolve_hostname(hostname: str) -> list[str]:
    """Resolve hostname to IP addresses with a short TTL cache.

    Caches results for 60 seconds to avoid repeated DNS lookups on
    every webhook delivery while keeping the window for DNS rebinding
    attacks small.
    """
    cached = _DNS_CACHE.get(hostname)
    if cached and time.monotonic() < cached[1]:
        return cached[0]

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}") from None

    ips = [sockaddr[0] for _, _, _, _, sockaddr in addr_info]
    _DNS_CACHE[hostname] = (ips, time.monotonic() + _DNS_TTL)
    return ips


def _is_blocked(ip_str: str) -> bool:
    """True for any address the server must not call on a user's behalf.

    Anything not globally routable is refused. The earlier test listed private,
    loopback, link-local and reserved, and let through 100.64.0.0/10 (carrier
    NAT, which is also the address range of a Tailscale network) and multicast.
    """
    ip = ipaddress.ip_address(ip_str)
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return not ip.is_global or ip.is_multicast


def blocked_url_target(url: str) -> str | None:
    """Return the blocked address a URL points at, or None.

    The strict check below refuses three different things: a URL with no
    hostname, a hostname that will not resolve, and a hostname that resolves
    into a range the server refuses to call. Only the third is a settled fact
    about the address. A name that does not resolve right now may resolve in an
    hour, so a form that saves a webhook must not refuse it on that ground —
    while the delivery step, which has to decide there and then, must.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return None
    try:
        ips = _resolve_hostname(hostname)
    except ValueError:
        return None
    for ip_str in ips:
        if _is_blocked(ip_str):
            return ip_str
    return None


def validate_url_not_private(url: str) -> None:
    """Validate that a URL does not resolve to a private/internal IP.

    Prevents SSRF by refusing every address that is not globally routable
    (see :func:`_is_blocked`). Uses a short DNS cache to avoid per-request
    resolution overhead. A caller that then connects must use
    :func:`pin_public_url`, or it resolves the name a second time.

    Raises:
        ValueError: If the URL has no hostname, cannot be resolved,
            or resolves to a blocked IP range.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Invalid URL: no hostname in {url}")

    ips = _resolve_hostname(hostname)

    for ip_str in ips:
        if _is_blocked(ip_str):
            raise ValueError(f"URL resolves to blocked IP range: {ip_str}")


def pin_public_url(url: str) -> tuple[str, str, str]:
    """Check a URL's address once and return a URL that connects to that address.

    Returns ``(pinned_url, host_header, hostname)``. The caller sends to
    ``pinned_url`` with ``Host: host_header`` and, for https, the TLS server
    name ``hostname``, so the certificate is still checked against the name.

    The name used to be resolved twice: once here to check it, and again by
    the HTTP client when it connected. A name with a zero TTL could answer a
    public address to the first lookup and ``127.0.0.1`` or a LAN address to
    the second, and the webhook was posted inside the network.

    Raises:
        ValueError: as :func:`validate_url_not_private`.
    """
    validate_url_not_private(url)
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    # IPv4 first: the workers may have no IPv6 route, and the HTTP client no
    # longer gets the chance to fall back to another address by itself.
    ips = sorted(dict.fromkeys(_resolve_hostname(hostname)), key=lambda a: ":" in a)
    address = ips[0]
    port = f":{parsed.port}" if parsed.port else ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = (f"[{address}]" if ":" in address else address) + port
    userinfo = parsed.netloc.rpartition("@")[0]
    if userinfo:
        netloc = f"{userinfo}@{netloc}"
    return parsed._replace(netloc=netloc).geturl(), host + port, hostname
