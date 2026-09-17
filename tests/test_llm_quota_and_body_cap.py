"""Per-user LLM quota (H5) and request-body cap (C3).

H5: there was no `limiter.limit` decorator anywhere in api/, so the only control
on LLM spend was the per-IP default — which C2 showed was bypassable. A quota
keyed on the Supabase `sub` survives IP rotation.

C3: Starlette buffers the whole body before deserialization, and the VM has
512MB, so one large POST OOM-killed the single process.
"""
import importlib

import pytest

from src import auth


@pytest.fixture()
def main(monkeypatch):
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    import api.main as m
    importlib.reload(m)
    return m


@pytest.fixture()
def client(main):
    from fastapi.testclient import TestClient
    return TestClient(main.app)


class _Req:
    def __init__(self, headers, client_host="10.0.0.1"):
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.client = type("C", (), {"host": client_host})()


# --- H5: the quota key follows the user, not the IP ----------------------

def test_user_key_is_the_supabase_subject(main, monkeypatch):
    monkeypatch.setattr(auth, "verify_supabase_jwt", lambda tok: {"sub": "user-1"})
    req = _Req({"Authorization": "Bearer good.token", "Fly-Client-IP": "203.0.113.7"})
    assert main._user_key(req) == "user:user-1"


def test_user_key_is_stable_across_rotated_ips(main, monkeypatch):
    """IP rotation must not hand the same account a fresh LLM budget."""
    monkeypatch.setattr(auth, "verify_supabase_jwt", lambda tok: {"sub": "user-1"})
    a = _Req({"Authorization": "Bearer t", "Fly-Client-IP": "203.0.113.7"})
    b = _Req({"Authorization": "Bearer t", "Fly-Client-IP": "198.51.100.2"})
    assert main._user_key(a) == main._user_key(b)


def test_user_key_falls_back_to_ip_when_unauthenticated(main, monkeypatch):
    monkeypatch.setattr(auth, "verify_supabase_jwt", lambda tok: None)
    req = _Req({"Fly-Client-IP": "203.0.113.7"})
    assert main._user_key(req) == "203.0.113.7"


def test_every_llm_route_declares_its_own_quota(main):
    """LLM spenders must not inherit only the (bypassable) per-IP default."""
    registered = set(main.limiter._route_limits)
    for endpoint in (
        "api.main.explain_post",
        "api.chat.chat",
        "api.chat.chat_captain",
        "api.chat.chat_transfer",
        "api.chat.chat_chip",
    ):
        assert endpoint in registered, f"{endpoint} has no explicit rate limit"


@pytest.fixture()
def _restore_modules():
    """Reloading api.main bakes env into module state — undo it for later tests."""
    yield
    import importlib as _il
    import src.ratelimit, api.chat, api.main
    _il.reload(src.ratelimit)
    _il.reload(api.chat)
    _il.reload(api.main)


def test_llm_quota_actually_returns_429(monkeypatch, _restore_modules):
    """Behavioural: the second call inside the window is refused.

    Unauthenticated is fine — the limiter decorator runs before the handler's
    auth check, so this exercises the limit without any upstream network call.
    """
    monkeypatch.setenv("FPL_LLM_RATE_LIMIT", "1/hour")
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    import src.ratelimit
    importlib.reload(src.ratelimit)
    import api.chat
    importlib.reload(api.chat)
    import api.main as m
    importlib.reload(m)
    from fastapi.testclient import TestClient

    client = TestClient(m.app)
    first = client.post("/explain", json={}, headers={"Fly-Client-IP": "203.0.113.9"})
    second = client.post("/explain", json={}, headers={"Fly-Client-IP": "203.0.113.9"})

    assert first.status_code == 401, "first call should reach the handler's auth check"
    assert second.status_code == 429, "second call should be rate limited"


# --- C3: oversized bodies are refused before they are buffered ----------

def test_oversized_body_is_refused(client, main):
    body = b"x" * (main.MAX_REQUEST_BYTES + 1)
    res = client.post("/squad/manual", content=body,
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 413


def test_normal_body_still_reaches_auth(client):
    """A small body must be rejected on auth (401), not on size."""
    res = client.post("/squad/manual", json={"entry_id": 1})
    assert res.status_code == 401
