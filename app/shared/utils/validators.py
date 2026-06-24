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


def validate_url_not_private(url: str) -> None:
    """Validate that a URL does not resolve to a private/internal IP.

    Prevents SSRF by blocking RFC 1918, loopback, link-local, and
    reserved IP ranges. Uses a short DNS cache to avoid per-request
    resolution overhead.

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
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"URL resolves to blocked IP range: {ip}")
