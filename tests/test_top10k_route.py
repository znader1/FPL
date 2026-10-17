"""POST /admin/refresh-top10k: admin-key gated; skips when the file already
holds the current GW; writes the sample otherwise."""
import importlib
import json

import pytest


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    monkeypatch.setenv("FPL_ADMIN_KEY", "adm1n")
    from src import config
    monkeypatch.setattr(config, "TOP10K_EO_PATH", str(tmp_path / "top10k_eo.json"))
    from fastapi.testclient import TestClient
    import api.main as main
    importlib.reload(main)
    bootstrap = {"total_players": 12_000_000, "events": [
        {"id": 6, "is_current": True, "is_next": False, "deadline_time": "2026-10-03T10:00:00Z", "finished": True},
        {"id": 7, "is_current": False, "is_next": True, "deadline_time": "2026-10-18T10:00:00Z", "finished": False},
    ]}
    monkeypatch.setattr(main, "get_bootstrap_cached", lambda: bootstrap)
    return TestClient(main.app), main, tmp_path / "top10k_eo.json"


def test_requires_the_admin_key(client):
    c, _, _ = client
    assert c.post("/admin/refresh-top10k", json={}).status_code in (401, 503)


def test_samples_the_current_gw_and_writes_the_file(client, monkeypatch):
    c, main, path = client
    from src import top10k_eo
    calls = []

    def fake_build(event_id, season, pages=None, **kw):
        calls.append((event_id, season, pages))
        return {"season": season, "event_id": event_id, "league_id": 314, "sample_n": 2, "errors": 0,
                "sampled_at_utc": "2026-10-16T10:00:00Z", "players": {1: {"owned_pct": 100.0, "captained_pct": 50.0, "eo_pct": 150.0}},
                "entries": [{"entry": 11, "rank": 1, "picks": [[1, 2]]}]}

    monkeypatch.setattr(top10k_eo, "build_sample", fake_build)
    res = c.post("/admin/refresh-top10k", json={}, headers={"X-API-Key": "adm1n"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] and body["skipped"] is False
    # Two samples: the top 10k (default pages) and the whole field (pages spread over total_players).
    assert calls[0] == (6, "2026-27", None)
    assert calls[1][:2] == (6, "2026-27") and calls[1][2] == top10k_eo.page_spread(12_000_000, main.config.FIELD_OVERALL_SAMPLE_ENTRIES)
    assert body["event_id"] == 6 and body["sample_n"] == 2 and body["overall_n"] == 2
    written = json.loads(path.read_text())
    assert written["players"]["1"]["eo_pct"] == 150.0
    assert written["entries"][0]["picks"] == [[1, 2]]
    assert written["overall"]["entries"][0]["picks"] == [[1, 2]] and written["overall"]["sample_n"] == 2


def test_overall_sample_failure_keeps_the_top10k_sample(client, monkeypatch):
    c, main, path = client
    from src import top10k_eo

    def fake_build(event_id, season, pages=None, **kw):
        if pages is not None:
            raise RuntimeError("403 blocked")
        return {"season": season, "event_id": event_id, "league_id": 314, "sample_n": 1, "errors": 0, "sampled_at_utc": "x", "players": {}, "entries": []}

    monkeypatch.setattr(top10k_eo, "build_sample", fake_build)
    res = c.post("/admin/refresh-top10k", json={}, headers={"X-API-Key": "adm1n"})
    assert res.status_code == 200, res.text
    assert res.json()["ok"] and res.json()["overall_n"] is None
    assert json.loads(path.read_text())["overall"] is None


def test_skips_when_the_file_already_holds_the_gw(client, monkeypatch):
    c, main, path = client
    from src import top10k_eo
    path.write_text(json.dumps({"season": "2026-27", "event_id": 6, "sample_n": 5, "players": {}}))
    monkeypatch.setattr(top10k_eo, "build_sample", lambda *a, **k: pytest.fail("must not sample"))
    res = c.post("/admin/refresh-top10k", json={}, headers={"X-API-Key": "adm1n"})
    assert res.status_code == 200 and res.json()["skipped"] is True


def test_force_resamples(client, monkeypatch):
    c, main, path = client
    from src import top10k_eo
    path.write_text(json.dumps({"season": "2026-27", "event_id": 6, "sample_n": 5, "players": {}}))
    monkeypatch.setattr(top10k_eo, "build_sample", lambda event_id, season, **k: {"season": season, "event_id": event_id, "league_id": 314, "sample_n": 1, "errors": 0, "sampled_at_utc": "x", "players": {}})
    res = c.post("/admin/refresh-top10k", json={"force": True}, headers={"X-API-Key": "adm1n"})
    assert res.status_code == 200 and res.json()["skipped"] is False and res.json()["sample_n"] == 1
