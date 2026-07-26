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


def _legal_15(client):
    # Team-aware greedy: fill the position quota respecting the 3-per-team cap.
    pool = client.post("/squad-picker/players", json={"projection_basis": "ppg"}).json()["players"]
    need = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    chosen, team_ct = [], {}
    for pl in sorted(pool, key=lambda x: -x["xpts_horizon"]):
        pos = pl["pos"]
        if need.get(pos, 0) <= 0:
            continue
        if team_ct.get(pl["team_id"], 0) >= 3:
            continue
        chosen.append(pl["player_id"])
        need[pos] -= 1
        team_ct[pl["team_id"]] = team_ct.get(pl["team_id"], 0) + 1
    return chosen


def test_lineup_legal_squad_optimizes(monkeypatch):
    client = _client(monkeypatch)
    ids = _legal_15(client)
    assert len(ids) == 15
    r = client.post("/squad-picker/lineup",
                    json={"player_ids": ids, "params": {"budget_m": 1000.0, "projection_basis": "ppg"}})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True, body.get("violations")
    assert len(body["starting_xi"]) == 11
    assert body["captain_player_id"] is not None


def test_lineup_xi_objectives(monkeypatch):
    client = _client(monkeypatch)
    ids = _legal_15(client)

    def lineup(obj):
        return client.post("/squad-picker/lineup", json={
            "player_ids": ids,
            "params": {"budget_m": 1000.0, "projection_basis": "ppg", "xi_objective": obj},
        }).json()

    horizon = lineup("horizon")
    assert horizon["valid"] is True and horizon["xi_objective"] == "horizon"
    assert len(horizon["starting_xi"]) == 11

    nxt = lineup("next_gw")
    assert nxt["xi_objective"] == "next_gw" and len(nxt["starting_xi"]) == 11

    per = lineup("per_gw")
    assert per["xi_objective"] == "per_gw"
    assert len(per["per_gw_lineups"]) >= 1
    assert all(len(g["starting_xi"]) == 11 for g in per["per_gw_lineups"])
    # rotating the XI each GW can only match or beat keeping the opener's XI
    assert per["rotation_gain"] >= -0.01


def test_lineup_defaults_to_horizon(monkeypatch):
    client = _client(monkeypatch)
    ids = _legal_15(client)
    body = client.post("/squad-picker/lineup",
                       json={"player_ids": ids, "params": {"budget_m": 1000.0}}).json()
    assert body["xi_objective"] == "horizon"


def test_lineup_bad_quota_reports_violation(monkeypatch):
    client = _client(monkeypatch)
    ids = _legal_15(client)[:-1]  # 14 players
    r = client.post("/squad-picker/lineup",
                    json={"player_ids": ids, "params": {"budget_m": 1000.0}})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert any("15" in v or "FWD" in v for v in body["violations"])


def test_lineup_over_budget_reports_violation(monkeypatch):
    client = _client(monkeypatch)
    ids = _legal_15(client)
    r = client.post("/squad-picker/lineup",
                    json={"player_ids": ids, "params": {"budget_m": 1.0}})
    body = r.json()
    assert body["valid"] is False
    assert any("budget" in v.lower() for v in body["violations"])


def test_players_endpoint_includes_fixtures(monkeypatch):
    client = _client(monkeypatch)
    r = client.post("/squad-picker/players", json={"horizon_gws": 5, "projection_basis": "ppg"})
    row = r.json()["players"][0]
    for k in ["fixtures", "avg_diff", "home_games"]:
        assert k in row
    if row["fixtures"]:
        assert {"gw", "opp", "home", "diff"}.issubset(row["fixtures"][0].keys())


def test_gk_rotation_pairs(monkeypatch):
    client = _client(monkeypatch)
    r = client.post("/squad-picker/gk-pairs",
                    json={"gk_pair_min_minutes": 0, "gk_pair_budget": 20, "projection_basis": "ppg"})
    assert r.status_code == 200
    pairs = r.json()["pairs"]
    assert len(pairs) > 0
    p = pairs[0]
    assert len(p["player_ids"]) == 2 and p["player_ids"][0] != p["player_ids"][1]
    assert p["teams"][0] != p["teams"][1]  # different teams
    assert p["rotation_xpts"] >= 0


def test_player_knowledge_get_post_roundtrip(tmp_path, monkeypatch):
    pk = tmp_path / "player_knowledge.json"
    monkeypatch.setattr(sr, "PLAYER_KNOWLEDGE_PATH", str(pk))
    app = FastAPI(); app.include_router(sr.router)
    client = TestClient(app)
    assert client.get("/squad-picker/player-knowledge").json() == {"as_of": None, "players": {}}
    p = client.post("/squad-picker/player-knowledge",
                    json={"as_of": "2026-07-26", "players": {"5": {"availability": 0.0, "note": "out"}}})
    assert p.status_code == 200
    got = client.get("/squad-picker/player-knowledge").json()
    assert got["players"]["5"]["note"] == "out"


def test_players_endpoint_carries_pk_fields(monkeypatch):
    client = _client(monkeypatch)
    r = client.post("/squad-picker/players", json={"horizon_gws": 5, "projection_basis": "ppg"})
    row = r.json()["players"][0]
    assert "pk_availability" in row and "pk_note" in row


def test_digest_news_empty_kb(monkeypatch):
    client = _client(monkeypatch)
    r = client.post("/squad-picker/digest-news", json={"kb_dir": "does/not/exist"})
    assert r.status_code == 200
    body = r.json()
    assert body["article_count"] == 0
    assert body["bootstrap_flags"] == 0
    assert body["proposals"]["players"] == {}


def test_digest_news_flags_bootstrap_injury(monkeypatch):
    # A-path: an injured player in the live bootstrap is proposed even with no
    # news corpus and no LLM.
    boot = _minimal_bootstrap()
    boot["elements"][0]["status"] = "i"
    boot["elements"][0]["news"] = "Groin injury - Expected back 21 Aug"
    boot["events"] = [
        {"id": 1, "is_next": True, "is_current": False, "deadline_time": "2026-08-15T17:30:00Z"},
        {"id": 2, "is_next": False, "is_current": False, "deadline_time": "2026-08-22T17:30:00Z"},
    ]
    injured_id = str(boot["elements"][0]["id"])
    monkeypatch.setattr(sr.fpl_client, "get_bootstrap", lambda: boot)
    monkeypatch.setattr(sr.fpl_client, "get_fixtures", lambda: _minimal_fixtures_raw())
    app = FastAPI(); app.include_router(sr.router)
    client = TestClient(app)

    r = client.post("/squad-picker/digest-news", json={"kb_dir": "does/not/exist"})
    assert r.status_code == 200
    body = r.json()
    assert body["bootstrap_flags"] == 1
    entry = body["proposals"]["players"][injured_id]
    assert entry["source"] == "fpl_bootstrap"
    assert entry["available_from_gw"] == 2
