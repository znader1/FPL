import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.squad_router as sr
from tests.test_squad_draft import _minimal_bootstrap, _minimal_fixtures_raw


def _client(monkeypatch):
    monkeypatch.setattr(sr.fpl_client, "get_bootstrap", lambda: _minimal_bootstrap())
    monkeypatch.setattr(sr.fpl_client, "get_fixtures", lambda: _minimal_fixtures_raw())
    app = FastAPI()
    app.include_router(sr.router)
    return TestClient(app)


def test_build_endpoint_returns_legal_squad(monkeypatch):
    client = _client(monkeypatch)
    r = client.post("/squad-picker/build", json={"horizon_gws": 5, "budget_m": 100.0,
                                          "projection_basis": "ppg"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["squad"]) == 15
    assert "projected_points" in body
