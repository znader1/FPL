"""Every /chat route answers 200 through the rate limiter.

The limiter runs with headers_enabled=True (src/ratelimit.py). For an endpoint
that returns a model instead of a Response, slowapi writes the X-RateLimit-*
headers onto the endpoint's ``response`` argument — and raises when there is
none. The chat routes had no ``response`` parameter, so every call failed with
a 500 *after* the Anthropic call had already been paid for.

These tests go through the real app, auth and limiter; only the context build
and the LLM agents are stubbed.
"""
import importlib

import pytest

import agents.captain_agent
import agents.chip_agent
import agents.orchestrator
import agents.transfer_agent
from api import chat
from src.ratelimit import limiter

SERVICE_KEY = "test-service-key"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("FPL_API_KEY", SERVICE_KEY)
    import api.main as main
    importlib.reload(main)
    limiter.reset()

    ctx = {
        "squad": [], "market": [], "starting_xi": [], "gw_projections": {},
        "bank_m": 0.0, "free_transfers": 1, "captain_id": 1, "fixtures": [], "breaks": [],
    }
    monkeypatch.setattr(chat, "_build_context_for_entry", lambda *a, **k: ctx)
    monkeypatch.setattr(chat, "_get_entry_chips", lambda *a, **k: [])
    monkeypatch.setattr(agents.captain_agent, "run_captain_agent", lambda **k: "captain answer")
    monkeypatch.setattr(agents.transfer_agent, "run_transfer_agent", lambda **k: "transfer answer")
    monkeypatch.setattr(agents.chip_agent, "run_chip_agent", lambda **k: "chip answer")
    monkeypatch.setattr(agents.orchestrator, "run_orchestrator", lambda **k: "orchestrator answer")

    from fastapi.testclient import TestClient
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.mark.parametrize("path, body, answer", [
    ("/chat/captain", {"entry_id": 1, "current_gw": 6}, "captain answer"),
    ("/chat/transfer", {"entry_id": 1, "current_gw": 6}, "transfer answer"),
    ("/chat/chip", {"entry_id": 1, "current_gw": 6}, "chip answer"),
    ("/chat", {"entry_id": 1, "current_gw": 6, "message": "who to captain?"}, "orchestrator answer"),
])
def test_chat_route_returns_200_with_rate_limit_headers(client, path, body, answer):
    r = client.post(path, json=body, headers={"X-API-Key": SERVICE_KEY})
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == answer
    assert "x-ratelimit-limit" in {h.lower() for h in r.headers}


def test_chat_route_still_requires_auth(client):
    r = client.post("/chat/captain", json={"entry_id": 1, "current_gw": 6})
    assert r.status_code == 401
