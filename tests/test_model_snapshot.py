import pandas as pd
from fastapi.testclient import TestClient

import api.main as m
from api.main import app

client = TestClient(app)


def test_model_snapshot_requires_admin_key(monkeypatch):
    # /admin/model-snapshot must gate exactly like /admin/refresh does when no
    # admin key is configured/presented. In this test environment neither
    # FPL_ADMIN_KEY nor FPL_API_KEY is set, so check_admin_key fails closed
    # with 503 ("Admin key not configured") rather than 401 — verify against
    # the real /admin/refresh route instead of assuming a status code.
    monkeypatch.delenv("FPL_ADMIN_KEY", raising=False)
    monkeypatch.delenv("FPL_API_KEY", raising=False)

    expected_status = client.post("/admin/refresh").status_code
    assert expected_status == 503  # documents the fail-closed behaviour relied on below

    r = client.get("/admin/model-snapshot")
    assert r.status_code == expected_status


def test_model_snapshot_payload_shape(monkeypatch):
    monkeypatch.setenv("FPL_ADMIN_KEY", "test-admin-key")

    bootstrap = {
        "events": [
            {"id": 1, "finished": True, "deadline_time": "2026-08-21T17:00:00Z"},
            {"id": 2, "is_next": True, "finished": False,
             "deadline_time": "2026-08-28T17:30:00Z"},
        ],
        "elements": [
            {"id": 480, "web_name": "Gibbs-White", "element_type": 3, "team": 16,
             "now_cost": 80, "selected_by_percent": "12.4", "status": "d",
             "chance_of_playing_next_round": 75, "ep_next": "4.5"},
        ],
        "teams": [{"id": 16, "short_name": "NFO"}],
        "element_types": [{"id": 3, "singular_name_short": "MID"}],
    }
    monkeypatch.setattr(m, "get_bootstrap_cached", lambda: bootstrap)
    monkeypatch.setattr(m, "get_fixtures_cached", lambda: pd.DataFrame(
        [{"event": 2, "team_h": 16, "team_a": 1}]))
    monkeypatch.setattr(
        m.projections, "project_elements_next_gws",
        lambda **kw: pd.DataFrame([{"id": 480, "xpts_gw2": 5.1}]),
    )

    r = client.get("/admin/model-snapshot", headers={"X-API-Key": "test-admin-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["next_gw"] == 2
    assert body["season"] == "2026-27"
    assert body["deadline_utc"].startswith("2026-08-28")
    assert isinstance(body["blend_weight"], float)
    assert body["finished_gws"] == [1]
    p = body["players"][0]
    assert p["player_id"] == 480
    assert p["model_xpts"] == 5.1
    assert p["fpl_ep_next"] == 4.5
    assert p["pos"] == "MID"
    assert p["team_short"] == "NFO"
    assert p["price_m"] == 8.0
    assert p["ownership_pct"] == 12.4
    assert p["chance"] == 75
