"""Phase 3.2 — GET /admin/data-status: age of every data source vs a threshold.

The builder is pure over injected inputs; the collector reads the real files
under a base directory; the route is admin-key gated.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from src import config, data_status

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _bootstrap(finished=5, next_gw=6):
    events = []
    for gw in range(1, 39):
        events.append({
            "id": gw,
            "finished": gw <= finished,
            "data_checked": gw <= finished,
            "is_next": gw == next_gw,
            "deadline_time": "2026-10-10T10:00:00Z",
        })
    return {"events": events}


def _healthy_inputs(**over):
    base = dict(
        now=NOW,
        bootstrap=_bootstrap(),
        refresh_receipt={"ok": True, "cache_refreshed_at_utc": _iso(NOW - timedelta(hours=2))},
        player_gw_history={"path": "x/player_gw_history_5.csv", "max_gw": 5,
                           "modified_at": NOW - timedelta(hours=2)},
        match_history={"path": "x/player_match_history_2026-27.csv", "max_event": 5, "rows": 1000},
        team_ratings={1: {"source": "blend", "samples": 4.0}, 2: {"source": "live", "samples": 9.0}},
        odds_cache={"ts": (NOW - timedelta(hours=1)).timestamp()},
        knowledge_discount={"as_of": "2026-10-01", "teams": {"ARS": {}}},
        player_knowledge={"as_of": "2026-10-04", "players": {"x": {}}},
        european_calendar={"as_of": "2026-09-17", "teams": {"ARS": "ucl"}},
        news_latest_at=NOW - timedelta(days=1),
    )
    base.update(over)
    return base


# --- builder ---------------------------------------------------------------

def test_healthy_inputs_are_ok():
    out = data_status.build_data_status(**_healthy_inputs())
    assert out["ok"] is True
    assert out["stale"] == [] and out["warnings"] == []
    assert out["finished_gw"] == 5 and out["next_gw"] == 6
    assert out["checked_at_utc"] == _iso(NOW)
    assert out["sources"]["player_gw_history"]["status"] == "ok"
    assert out["sources"]["player_gw_history"]["lag_gws"] == 0


def test_player_gw_history_lagging_a_gw_is_not_ok():
    out = data_status.build_data_status(**_healthy_inputs(
        player_gw_history={"path": "x/player_gw_history_4.csv", "max_gw": 4,
                           "modified_at": NOW - timedelta(days=3)}))
    assert out["ok"] is False
    assert "player_gw_history" in out["stale"]
    assert out["sources"]["player_gw_history"]["lag_gws"] == 1


def test_match_history_lagging_a_gw_is_not_ok():
    out = data_status.build_data_status(**_healthy_inputs(
        match_history={"path": "x", "max_event": 3, "rows": 10}))
    assert out["ok"] is False
    assert out["sources"]["match_history"]["lag_gws"] == 2


def test_missing_history_is_not_ok():
    out = data_status.build_data_status(**_healthy_inputs(player_gw_history=None, match_history=None))
    assert out["ok"] is False
    assert out["sources"]["player_gw_history"]["status"] == "missing"
    assert out["sources"]["match_history"]["status"] == "missing"


def test_refresh_receipt_too_old_or_failed_is_not_ok(monkeypatch):
    monkeypatch.setattr(config, "DATA_STATUS_REFRESH_MAX_AGE_H", 9)
    old = data_status.build_data_status(**_healthy_inputs(
        refresh_receipt={"ok": True, "cache_refreshed_at_utc": _iso(NOW - timedelta(hours=10))}))
    assert old["ok"] is False and "refresh" in old["stale"]
    assert old["sources"]["refresh"]["age_hours"] == pytest.approx(10.0)
    failed = data_status.build_data_status(**_healthy_inputs(
        refresh_receipt={"ok": False, "error": "fpl down", "failed_at_utc": _iso(NOW)}))
    assert failed["ok"] is False
    assert failed["sources"]["refresh"]["status"] == "failed"
    assert failed["sources"]["refresh"]["error"] == "fpl down"
    missing = data_status.build_data_status(**_healthy_inputs(refresh_receipt={}))
    assert missing["ok"] is False and missing["sources"]["refresh"]["status"] == "missing"


def test_ratings_all_carryover_after_gw1_is_a_warning():
    out = data_status.build_data_status(**_healthy_inputs(
        team_ratings={1: {"source": "carryover", "samples": 0.0}, 2: {"source": "carryover", "samples": 0.0}}))
    assert out["ok"] is True  # soft signal: the engine still runs
    assert "team_ratings" in out["warnings"]
    src = out["sources"]["team_ratings"]
    assert src["by_source"] == {"carryover": 2}
    assert src["live_teams"] == 0


def test_ratings_ignore_the_league_scalar():
    out = data_status.build_data_status(**_healthy_inputs(
        team_ratings={"_league": 1.4, 1: {"source": "live", "samples": 5.0}}))
    assert out["sources"]["team_ratings"]["teams"] == 1
    assert out["sources"]["team_ratings"]["status"] == "ok"


def test_ratings_carryover_preseason_is_fine():
    out = data_status.build_data_status(**_healthy_inputs(
        bootstrap=_bootstrap(finished=0, next_gw=1),
        player_gw_history=None, match_history=None,
        team_ratings={1: {"source": "carryover", "samples": 0.0}}))
    assert "team_ratings" not in out["warnings"]
    # No finished GW → nothing can lag; missing history is expected pre-season.
    assert out["ok"] is True


def test_optional_sources_warn_but_do_not_fail(monkeypatch):
    monkeypatch.setattr(config, "PLAYER_KNOWLEDGE_STALE_DAYS", 10)
    monkeypatch.setattr(config, "DATA_STATUS_KNOWLEDGE_DISCOUNT_STALE_DAYS", 14)
    monkeypatch.setattr(config, "DATA_STATUS_NEWS_STALE_DAYS", 7)
    out = data_status.build_data_status(**_healthy_inputs(
        odds_cache=None,
        knowledge_discount={"as_of": "2026-09-01", "teams": {}},
        player_knowledge={},
        european_calendar={"as_of": "2026-09-17", "teams": {}},
        news_latest_at=None,
    ))
    assert out["ok"] is True
    assert set(out["warnings"]) == {
        "odds", "knowledge_discount", "player_knowledge", "european_calendar", "news"}
    assert out["sources"]["odds"]["status"] == "missing"
    assert out["sources"]["knowledge_discount"]["age_days"] == 35
    assert out["sources"]["player_knowledge"]["status"] == "missing"
    assert out["sources"]["european_calendar"]["teams"] == 0
    assert out["sources"]["european_calendar"]["note"]


def test_odds_cache_older_than_ttl_warns(monkeypatch):
    monkeypatch.setattr(config, "ODDS_CACHE_TTL_S", 3600.0)
    out = data_status.build_data_status(**_healthy_inputs(
        odds_cache={"ts": (NOW - timedelta(hours=2)).timestamp()}))
    assert "odds" in out["warnings"]
    assert out["sources"]["odds"]["status"] == "stale"


def test_garbage_dates_do_not_raise():
    out = data_status.build_data_status(**_healthy_inputs(
        refresh_receipt={"ok": True, "cache_refreshed_at_utc": "not a date"},
        knowledge_discount={"as_of": 12345},
    ))
    assert out["sources"]["refresh"]["status"] == "missing"
    assert out["sources"]["knowledge_discount"]["status"] == "missing"


# --- collector reads real files -------------------------------------------

def test_collect_reads_files_under_base_dir(tmp_path, monkeypatch):
    proc = tmp_path / "data" / "processed" / "fpl"
    (proc / "2026-10-05").mkdir(parents=True)
    (proc / "2026-10-05" / "player_gw_history_5.csv").write_text("player_id,gw\n1,5\n")
    (proc / "2026-27").mkdir()
    (proc / "2026-27" / "player_match_history_2026-27.csv").write_text(
        "event,team_id\n1,1\n5,1\n")
    odds = tmp_path / "data" / "processed" / "odds"
    odds.mkdir()
    (odds / "latest.json").write_text(json.dumps({"ts": NOW.timestamp(), "data": []}))
    models = tmp_path / "data" / "models"
    models.mkdir()
    (models / "refresh_status.json").write_text(json.dumps(
        {"ok": True, "cache_refreshed_at_utc": _iso(NOW)}))
    (models / "knowledge_discount.json").write_text(json.dumps({"as_of": "2026-10-01", "teams": {}}))
    (models / "european_calendar.json").write_text(json.dumps({"as_of": "2026-09-17", "teams": {}}))
    news = tmp_path / "kb" / "auto" / "news"
    news.mkdir(parents=True)
    (news / "2026-10-05.md").write_text("x")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FPL_PLAYER_HISTORY_BASE_DIR", raising=False)
    inputs = data_status.collect_inputs(bootstrap=_bootstrap(), team_ratings={1: {"source": "blend", "samples": 2.0}}, now=NOW)
    assert inputs["player_gw_history"]["max_gw"] == 5
    assert inputs["match_history"]["max_event"] == 5
    assert inputs["match_history"]["rows"] == 2
    assert inputs["odds_cache"]["ts"] == pytest.approx(NOW.timestamp())
    assert inputs["refresh_receipt"]["ok"] is True
    assert inputs["knowledge_discount"]["as_of"] == "2026-10-01"
    assert inputs["player_knowledge"] == {}
    assert inputs["european_calendar"]["as_of"] == "2026-09-17"
    assert inputs["news_latest_at"] is not None

    out = data_status.build_data_status(**inputs)
    assert out["ok"] is True
    assert "player_knowledge" in out["warnings"]


def test_collect_with_nothing_on_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FPL_PLAYER_HISTORY_BASE_DIR", raising=False)
    inputs = data_status.collect_inputs(bootstrap=_bootstrap(), team_ratings={}, now=NOW)
    out = data_status.build_data_status(**inputs)
    assert out["ok"] is False
    assert set(out["stale"]) >= {"refresh", "player_gw_history", "match_history"}


# --- route -------------------------------------------------------------------

@pytest.fixture()
def status_client(monkeypatch):
    from fastapi.testclient import TestClient
    from api import main

    monkeypatch.setenv("FPL_ADMIN_KEY", "adm1n")
    monkeypatch.setattr(main, "get_bootstrap_cached", lambda: _bootstrap())
    monkeypatch.setattr(main, "get_team_ratings_cached", lambda teams_short_map: {1: {"source": "blend", "samples": 3.0}})
    monkeypatch.setattr(data_status, "collect_inputs", lambda bootstrap, team_ratings, now=None: _healthy_inputs(bootstrap=bootstrap, team_ratings=team_ratings))
    return TestClient(main.app)


def test_route_requires_admin_key(status_client):
    assert status_client.get("/admin/data-status").status_code == 401


def test_route_returns_status(status_client):
    res = status_client.get("/admin/data-status", headers={"X-API-Key": "adm1n"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["finished_gw"] == 5
    assert "player_gw_history" in body["sources"]


def test_route_gates_like_refresh(status_client, monkeypatch):
    # Same key policy as /admin/refresh: a user API key must not open it.
    monkeypatch.setenv("FPL_API_KEY", "user-key")
    assert status_client.get("/admin/data-status", headers={"X-API-Key": "user-key"}).status_code == 401
