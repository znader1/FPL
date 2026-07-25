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


def test_knowledge_get_and_post_roundtrip(tmp_path, monkeypatch):
    kb = tmp_path / "knowledge_discount.json"
    kb.write_text('{"as_of":"2026-06-10","teams":{}}')
    monkeypatch.setattr(sr, "KNOWLEDGE_PATH", str(kb))
    app = FastAPI(); app.include_router(sr.router)
    client = TestClient(app)

    g = client.get("/squad-picker/knowledge")
    assert g.status_code == 200 and g.json()["as_of"] == "2026-06-10"

    p = client.post("/squad-picker/knowledge",
                    json={"as_of": "2026-07-23",
                          "teams": {"COV": {"attack": 0.9, "defense": 1.1}}})
    assert p.status_code == 200
    assert client.get("/squad-picker/knowledge").json()["teams"]["COV"]["attack"] == 0.9


def test_players_endpoint_returns_full_pool(monkeypatch):
    client = _client(monkeypatch)
    r = client.post("/squad-picker/players", json={"horizon_gws": 5, "projection_basis": "ppg"})
    assert r.status_code == 200
    body = r.json()
    assert body["gw_start"] == 1 and body["horizon_gws"] == 5
    assert len(body["players"]) > 0
    row = body["players"][0]
    for k in ["player_id", "pos", "team_id", "price_m", "total_points",
              "xpts_horizon", "xpts_per_gw"]:
        assert k in row
    assert len(row["xpts_per_gw"]) == 5
