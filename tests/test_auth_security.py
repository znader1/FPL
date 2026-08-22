"""Security regression tests for request authentication.

These lock in the fail-closed behaviour: no valid credential => request denied.
"""
import importlib

import pytest
from fastapi.responses import JSONResponse

from src import auth


# --- unit: check_api_key -------------------------------------------------

def test_api_key_denies_when_nothing_presented(monkeypatch):
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    res = auth.check_api_key(x_api_key=None, authorization=None, api_key=None)
    assert isinstance(res, JSONResponse) and res.status_code == 401


def test_api_key_ignores_query_or_body_key(monkeypatch):
    """M2: keys must never be accepted via query string / body."""
    monkeypatch.setenv("FPL_API_KEY", "s3cret")
    # Presenting the correct value through the (query/body) api_key arg must fail.
    res = auth.check_api_key(x_api_key=None, authorization=None, api_key="s3cret")
    assert isinstance(res, JSONResponse) and res.status_code == 401


def test_api_key_accepts_static_header_key(monkeypatch):
    monkeypatch.setenv("FPL_API_KEY", "s3cret")
    assert auth.check_api_key(x_api_key="s3cret", authorization=None) is None


def test_api_key_accepts_valid_jwt(monkeypatch):
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    monkeypatch.setattr(auth, "verify_supabase_jwt", lambda tok: {"sub": "u1"})
    assert auth.check_api_key(authorization="Bearer good.token") is None


def test_api_key_rejects_invalid_jwt(monkeypatch):
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    monkeypatch.setattr(auth, "verify_supabase_jwt", lambda tok: None)
    res = auth.check_api_key(authorization="Bearer bad.token")
    assert isinstance(res, JSONResponse) and res.status_code == 401


# --- unit: check_admin_key ----------------------------------------------

def test_admin_fails_closed_when_unconfigured(monkeypatch):
    monkeypatch.delenv("FPL_ADMIN_KEY", raising=False)
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    res = auth.check_admin_key(x_api_key="anything")
    assert isinstance(res, JSONResponse) and res.status_code == 503


def test_admin_accepts_correct_key(monkeypatch):
    monkeypatch.setenv("FPL_ADMIN_KEY", "adm1n")
    assert auth.check_admin_key(x_api_key="adm1n") is None


def test_admin_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("FPL_ADMIN_KEY", "adm1n")
    res = auth.check_admin_key(x_api_key="nope")
    assert isinstance(res, JSONResponse) and res.status_code == 401


# --- integration: live routes reject anonymous callers -------------------

@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    monkeypatch.setenv("SQUAD_PICKER_MODE", "1")
    from fastapi.testclient import TestClient
    import api.main as main
    importlib.reload(main)
    return TestClient(main.app)


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_squad_requires_auth(client):
    assert client.get("/squad", params={"entry_id": 1}).status_code == 401


def test_chat_requires_auth(client):
    assert client.post("/chat", json={"entry_id": 1, "message": "hi"}).status_code == 401


def test_admin_refresh_requires_key(client):
    assert client.post("/admin/refresh", json={}).status_code in (401, 503)


def test_squad_picker_write_requires_admin(client):
    # logged-out => 401; knowledge write must never be anonymous
    assert client.post("/squad-picker/knowledge", json={"teams": {}}).status_code == 401
