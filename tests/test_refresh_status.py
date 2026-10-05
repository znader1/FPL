"""Phase 3.1 — the /admin/refresh receipt is persisted to disk.

Pure-module tests for src/refresh_status plus a route test that the refresh
endpoint writes the receipt on success and on upstream failure.
"""
import json
import os

import pytest

from src import config, refresh_status


# --- unit: write / read --------------------------------------------------

def test_write_creates_file_with_timestamp(tmp_path):
    path = tmp_path / "models" / "refresh_status.json"
    ok = refresh_status.write_refresh_status({"ok": True, "foo": 1}, path=path)
    assert ok is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ok"] is True and data["foo"] == 1
    assert data["written_at_utc"].endswith("Z")


def test_write_replaces_previous_receipt(tmp_path):
    path = tmp_path / "refresh_status.json"
    refresh_status.write_refresh_status({"ok": True, "n": 1}, path=path)
    refresh_status.write_refresh_status({"ok": False, "n": 2}, path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["n"] == 2 and data["ok"] is False
    # Atomic write: no temp file left behind.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["refresh_status.json"]


def test_write_failure_returns_false_and_does_not_raise(tmp_path, monkeypatch):
    path = tmp_path / "refresh_status.json"

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    assert refresh_status.write_refresh_status({"ok": True}, path=path) is False
    assert not path.exists()


def test_write_unserialisable_payload_returns_false(tmp_path):
    path = tmp_path / "refresh_status.json"
    assert refresh_status.write_refresh_status({"ok": object()}, path=path) is False
    assert not path.exists()


def test_read_missing_returns_empty(tmp_path):
    assert refresh_status.read_refresh_status(path=tmp_path / "nope.json") == {}


def test_read_corrupt_returns_empty(tmp_path):
    path = tmp_path / "refresh_status.json"
    path.write_text("{not json", encoding="utf-8")
    assert refresh_status.read_refresh_status(path=path) == {}


def test_default_path_comes_from_config(tmp_path, monkeypatch):
    target = tmp_path / "cfg" / "refresh_status.json"
    monkeypatch.setattr(config, "REFRESH_STATUS_PATH", str(target))
    assert refresh_status.write_refresh_status({"ok": True}) is True
    assert refresh_status.read_refresh_status()["ok"] is True


# --- route: /admin/refresh writes the receipt ----------------------------

@pytest.fixture()
def refresh_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main

    monkeypatch.setenv("FPL_ADMIN_KEY", "adm1n")
    target = tmp_path / "refresh_status.json"
    monkeypatch.setattr(config, "REFRESH_STATUS_PATH", str(target))

    bootstrap = {"events": [{"id": 6, "finished": False}], "elements": [], "teams": []}
    monkeypatch.setattr(main, "get_bootstrap_cached", lambda: bootstrap)
    monkeypatch.setattr(main, "get_fixtures_cached", lambda: [])
    monkeypatch.setattr(
        main, "build_next_event_summary", lambda bootstrap, fixtures: {"event_id": 6})
    monkeypatch.setattr(main, "get_projections_cached", lambda *a, **k: None)
    monkeypatch.setattr(main, "refresh_match_history", lambda b, f: {"appended": 0})
    monkeypatch.setattr(
        main.fpl_refresh_next_gw, "refresh_next_gw_snapshot", lambda out_base: {"rows": 1})
    import src.odds_client as odds_client
    monkeypatch.setattr(odds_client, "fetch_epl_odds", lambda: {})
    return TestClient(main.app, raise_server_exceptions=True), target


def test_refresh_route_writes_receipt_on_success(refresh_client):
    client, target = refresh_client
    res = client.post("/admin/refresh", headers={"X-API-Key": "adm1n"}, json={})
    assert res.status_code == 200, res.text
    body = res.json()
    receipt = json.loads(target.read_text(encoding="utf-8"))
    assert receipt["ok"] is True
    assert receipt["next_event"] == {"event_id": 6}
    assert receipt["cache_refreshed_at_utc"] == body["cache_refreshed_at_utc"]
    assert receipt["snapshot_info"] == {"rows": 1}
    assert receipt["projections_warmed"] == body["projections_warmed"]
    assert "written_at_utc" in receipt


def test_refresh_route_writes_failure_receipt_and_still_raises(refresh_client, monkeypatch):
    from api import main

    client, target = refresh_client

    def boom():
        raise RuntimeError("fpl api down")

    monkeypatch.setattr(main, "get_bootstrap_cached", boom)
    with pytest.raises(RuntimeError, match="fpl api down"):
        client.post("/admin/refresh", headers={"X-API-Key": "adm1n"}, json={})
    receipt = json.loads(target.read_text(encoding="utf-8"))
    assert receipt["ok"] is False
    assert "fpl api down" in receipt["error"]
    assert receipt["failed_at_utc"].endswith("Z")


def test_refresh_route_survives_receipt_write_failure(refresh_client, monkeypatch):
    client, target = refresh_client
    monkeypatch.setattr(refresh_status, "write_refresh_status", lambda *a, **k: False)
    res = client.post("/admin/refresh", headers={"X-API-Key": "adm1n"}, json={})
    assert res.status_code == 200
    assert not target.exists()


def test_refresh_route_without_key_writes_nothing(refresh_client):
    client, target = refresh_client
    res = client.post("/admin/refresh", json={})
    assert res.status_code == 401
    assert not target.exists()
