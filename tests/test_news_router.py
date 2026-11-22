"""Admin endpoints for news auto-apply (run / status / revert)."""
import json

import pytest

from src import config, news_auto_run

H = {"X-API-Key": "adm1n"}


@pytest.fixture()
def nclient(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main

    monkeypatch.setenv("FPL_ADMIN_KEY", "adm1n")
    out = tmp_path / "news_auto"
    auto = tmp_path / "player_knowledge_auto.json"
    monkeypatch.setattr(config, "NEWS_AUTO_DIR", str(out))
    monkeypatch.setattr(config, "PLAYER_KNOWLEDGE_AUTO_PATH", str(auto))
    bootstrap = {"events": [{"id": 6, "finished": False, "is_next": True}],
                 "elements": [], "teams": []}
    monkeypatch.setattr(main, "get_bootstrap_cached", lambda: bootstrap)
    return TestClient(main.app, raise_server_exceptions=True), out, auto


def test_refresh_news_requires_admin(nclient):
    client, _, _ = nclient
    assert client.post("/admin/refresh-news").status_code == 401
    assert client.get("/admin/news-status").status_code == 401
    assert client.post("/admin/news-knowledge/revert",
                       json={"player_ids": ["1"]}).status_code == 401


def test_refresh_news_returns_202_and_runs(nclient, monkeypatch):
    import threading
    client, out, _ = nclient
    calls = []

    def fake_run(bootstrap, **kw):
        calls.append((bootstrap, kw))
        news_auto_run.release_lock(str(out), kw["run_id"])

    class Inline:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self.t = (target, args, kwargs or {})

        def start(self):
            self.t[0](*self.t[1], **self.t[2])

    monkeypatch.setattr(news_auto_run, "run", fake_run)
    monkeypatch.setattr(threading, "Thread", Inline)
    res = client.post("/admin/refresh-news", headers=H)
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["run_id"].endswith("Z") and "started" in body
    assert len(calls) == 1
    assert calls[0][1]["run_id"] == body["run_id"] and calls[0][1]["lock_held"] is True
    assert not (out / "run.lock").exists()


def test_refresh_news_409_when_locked(nclient):
    client, out, _ = nclient
    assert news_auto_run.acquire_lock(str(out), "other")
    res = client.post("/admin/refresh-news", headers=H)
    assert res.status_code == 409
    assert res.json() == {"detail": "news run already in progress"}


def test_refresh_news_thread_start_failure_releases_lock(nclient, monkeypatch):
    import threading
    client, out, _ = nclient

    class Bad:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("cannot start")

    monkeypatch.setattr(threading, "Thread", Bad)
    res = client.post("/admin/refresh-news", headers=H)
    assert res.status_code == 500
    assert "cannot start" not in res.text
    assert not (out / "run.lock").exists()


def test_news_status_shape(nclient):
    client, _, _ = nclient
    res = client.get("/admin/news-status", headers=H)
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"running", "last_run", "active"}
    assert body["running"] is False and body["active"] == {}


def _seed(auto):
    auto.write_text(json.dumps({"players": {
        "10": {"minutes_mult": 0.5, "run_id": "r1", "expires_after_gw": 7},
        "11": {"minutes_mult": 0.6, "run_id": "r2", "expires_after_gw": 7}}}))


def test_revert_by_player_writes_tombstone(nclient):
    client, out, auto = nclient
    _seed(auto)
    res = client.post("/admin/news-knowledge/revert", headers=H,
                      json={"player_ids": [10, "99"]})
    assert res.status_code == 200, res.text
    assert res.json() == {"reverted": ["10"]}
    data = json.loads(auto.read_text())
    assert "10" not in data["players"] and "11" in data["players"]
    assert data["tombstones"]["10"] == {"until_gw": 7}
    log = (out / "changes.jsonl").read_text().strip().splitlines()
    assert json.loads(log[0])["kind"] == "revert"
    assert not (out / "run.lock").exists()


def test_revert_by_run_id(nclient):
    client, _, auto = nclient
    _seed(auto)
    res = client.post("/admin/news-knowledge/revert", headers=H, json={"run_id": "r2"})
    assert res.status_code == 200
    assert res.json() == {"reverted": ["11"]}


@pytest.mark.parametrize("body", [
    {}, {"player_ids": ["1"], "run_id": "r1"}, {"player_ids": []},
    {"player_ids": ["../x"]}, {"player_ids": [1.5]}, {"player_ids": [True]},
    {"player_ids": "10"}, {"run_id": ""}, {"run_id": 5},
    {"run_id": "r1\n"}, {"player_ids": ["10\n"]},
])
def test_revert_requires_exactly_one_valid_selector(nclient, body):
    client, _, auto = nclient
    _seed(auto)
    assert client.post("/admin/news-knowledge/revert", headers=H, json=body).status_code == 422


def test_revert_409_while_locked(nclient):
    client, out, auto = nclient
    _seed(auto)
    assert news_auto_run.acquire_lock(str(out), "other")
    res = client.post("/admin/news-knowledge/revert", headers=H, json={"player_ids": ["10"]})
    assert res.status_code == 409
    assert "10" in json.loads(auto.read_text())["players"]
