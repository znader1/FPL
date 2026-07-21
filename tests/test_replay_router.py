import json
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "data" / "replay" / "2025-26"
    base.mkdir(parents=True)
    (base / "gw07.json").write_text(json.dumps({
        "season": "2025-26", "gw": 7, "setup_gw": False,
        "players": [{"element": 351, "model_xpts": 6.4, "actual_points": 12}],
        "model_captain": 351, "optimal_captain": 351,
        "suggested_transfer": None, "sp2_candidates": []}))
    (base / "entry_588004.json").write_text(json.dumps({
        "entry_id": 588004, "season": "2025-26",
        "gws": {"7": {"captain": 233, "transfers": {"in": [], "out": []},
                      "chip": None, "points": 61}}}))
    from api.replay_router import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_gw_endpoint_merges_your_side(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    r = client.get("/replay/2025-26/gw/7", params={"entry_id": 588004})
    assert r.status_code == 200
    body = r.json()
    assert body["model_captain"] == 351
    assert body["your"]["captain"] == 233 and body["your"]["points"] == 61


def test_missing_gw_is_404(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    r = client.get("/replay/2025-26/gw/99", params={"entry_id": 588004})
    assert r.status_code == 404
    assert "2025-26" in r.json()["detail"] and "99" in r.json()["detail"]


def test_seasons_lists_available(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    assert client.get("/replay/seasons").json()["seasons"] == ["2025-26"]


def test_bad_season_is_404(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    assert client.get("/replay/..%2F..%2Fetc/gw/7", params={"entry_id": 588004}).status_code == 404
    assert client.get("/replay/2025_26/gw/7", params={"entry_id": 588004}).status_code == 404
