"""A webhook is posted to the address that was checked, not to a second lookup.

The URL guard resolved the name and checked the addresses, and then the HTTP
client resolved the name again when it connected. A name with a zero TTL could
answer a public address to the first lookup and 127.0.0.1 to the second, and
the webhook went to a service inside the network (DNS rebinding).
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import pytest

from app.services import webhook_service
from app.shared.utils import validators
from app.shared.utils.validators import blocked_url_target

_REAL_GETADDRINFO = socket.getaddrinfo


def _addrinfo(ip: str, port: int = 0) -> list:
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (ip, port))]


@pytest.fixture(autouse=True)
def _empty_dns_cache():
    validators._DNS_CACHE.clear()
    yield
    validators._DNS_CACHE.clear()


def test_a_second_lookup_cannot_send_the_webhook_inside_the_network() -> None:
    hits: list[str] = []

    class _Internal(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), _Internal)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    answers = iter(["8.8.8.8", "127.0.0.1"])

    def rebinding_dns(host, port=None, *args, **kwargs):
        if host == "hook.rebind.example":
            return _addrinfo(next(answers, "127.0.0.1"), int(port or 0))
        return _REAL_GETADDRINFO(host, port, *args, **kwargs)

    try:
        with (
            patch("socket.getaddrinfo", side_effect=rebinding_dns),
            patch.object(webhook_service, "WEBHOOK_TIMEOUT", 1.0),
        ):
            webhook_service.deliver_webhook(
                f"http://hook.rebind.example:{port}/hook", {"event": "test"}
            )
    finally:
        server.shutdown()
        server.server_close()

    assert hits == [], "the webhook reached 127.0.0.1 through a second DNS answer"


def test_the_pinned_url_keeps_the_name_for_host_and_tls() -> None:
    from app.shared.utils.validators import pin_public_url

    with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
        url, host, server_name = pin_public_url("https://hooks.example.com:8443/in?x=1")

    assert url == "https://93.184.216.34:8443/in?x=1"
    assert host == "hooks.example.com:8443"
    assert server_name == "hooks.example.com"


def test_an_ipv6_address_is_bracketed_and_ipv4_is_preferred() -> None:
    from app.shared.utils.validators import pin_public_url

    both = _addrinfo("2606:2800:220:1:248:1893:25c8:1946") + _addrinfo("93.184.216.34")
    with patch("socket.getaddrinfo", return_value=both):
        url, _host, _name = pin_public_url("http://hooks.example.com/in")
    assert url == "http://93.184.216.34/in"

    validators._DNS_CACHE.clear()
    with patch("socket.getaddrinfo", return_value=both[:1]):
        url, _host, _name = pin_public_url("http://hooks.example.com/in")
    assert url == "http://[2606:2800:220:1:248:1893:25c8:1946]/in"


def test_the_delivery_sends_host_and_server_name() -> None:
    with (
        patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")),
        patch("app.services.webhook_service.httpx.Client") as client_cls,
    ):
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.status_code = 204
        assert webhook_service.deliver_webhook("https://hooks.example.com/in", {"event": "e"})

    call = client.post.call_args
    assert call.args[0] == "https://93.184.216.34/in"
    assert call.kwargs["headers"]["Host"] == "hooks.example.com"
    assert call.kwargs["extensions"] == {"sni_hostname": "hooks.example.com"}


@pytest.mark.parametrize(
    "address",
    [
        "100.64.3.7",  # carrier NAT, and every Tailscale address
        "224.0.0.251",  # multicast
        "::ffff:127.0.0.1",  # loopback written as IPv6
        "198.18.0.1",  # benchmarking range
        "10.1.2.3",
        "169.254.169.254",
    ],
)
def test_an_address_that_is_not_public_is_refused(address: str) -> None:
    from app.shared.utils.validators import pin_public_url

    with patch("socket.getaddrinfo", return_value=_addrinfo(address)):
        assert blocked_url_target("http://hooks.example.com/in") == address
        validators._DNS_CACHE.clear()
        with pytest.raises(ValueError):
            pin_public_url("http://hooks.example.com/in")
