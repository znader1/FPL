"""The rate-limit key must not be client-controlled (audit finding C2).

Fly's proxy *appends* the real client address to any inbound X-Forwarded-For
rather than replacing it, so `xff.split(",")[0]` is whatever the attacker sent.
Rotating that header defeated every limit in the app, LLM routes included.
`Fly-Client-IP` is set by the proxy and cannot be spoofed from outside.
"""
import importlib

import pytest


@pytest.fixture()
def main(monkeypatch):
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    import api.main as m
    importlib.reload(m)
    return m


class _Req:
    def __init__(self, headers, client_host="10.0.0.1"):
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.client = type("C", (), {"host": client_host})()


def test_prefers_fly_client_ip_over_spoofed_forwarded_for(main):
    req = _Req({
        "Fly-Client-IP": "203.0.113.7",
        "X-Forwarded-For": "1.2.3.4, 203.0.113.7",
    })
    assert main._client_ip(req) == "203.0.113.7"


def test_ignores_forwarded_for_entirely_when_fly_header_present(main):
    """An attacker rotating XFF must not move the bucket."""
    a = _Req({"Fly-Client-IP": "203.0.113.7", "X-Forwarded-For": "1.1.1.1"})
    b = _Req({"Fly-Client-IP": "203.0.113.7", "X-Forwarded-For": "2.2.2.2"})
    assert main._client_ip(a) == main._client_ip(b)


def test_uses_last_forwarded_hop_when_no_fly_header(main):
    """Off Fly, the proxy-appended right-most hop is the trustworthy one."""
    req = _Req({"X-Forwarded-For": "1.2.3.4, 198.51.100.9"})
    assert main._client_ip(req) == "198.51.100.9"


def test_falls_back_to_socket_address(main):
    assert main._client_ip(_Req({}, client_host="192.0.2.5")) == "192.0.2.5"
