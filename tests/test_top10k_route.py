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
    bootstrap = {"events": [
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

    def fake_build(event_id, season, **kw):
        calls.append((event_id, season))
        return {"season": season, "event_id": event_id, "league_id": 314, "sample_n": 2, "errors": 0,
                "sampled_at_utc": "2026-10-16T10:00:00Z", "players": {1: {"owned_pct": 100.0, "captained_pct": 50.0, "eo_pct": 150.0}}}

    monkeypatch.setattr(top10k_eo, "build_sample", fake_build)
    res = c.post("/admin/refresh-top10k", json={}, headers={"X-API-Key": "adm1n"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] and body["skipped"] is False
    assert calls == [(6, "2026-27")]
    assert body["event_id"] == 6 and body["sample_n"] == 2
    assert json.loads(path.read_text())["players"]["1"]["eo_pct"] == 150.0


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
