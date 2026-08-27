from datetime import datetime, timezone

from scripts.snapshot_to_db import snapshot_rows, actuals_rows

PAYLOAD = {
    "season": "2026-27", "next_gw": 2,
    "deadline_utc": "2026-08-28T17:30:00Z", "blend_weight": 0.5,
    "players": [{
        "player_id": 480, "web_name": "Gibbs-White", "pos": "MID",
        "team_short": "NFO", "price_m": 8.0, "ownership_pct": 12.4,
        "status": "d", "chance": 75, "fpl_ep_next": 4.5, "model_xpts": 5.1,
    }],
}


def test_snapshot_rows_before_deadline():
    now = datetime(2026, 8, 28, 16, 0, tzinfo=timezone.utc)
    rows = snapshot_rows(PAYLOAD, now)
    assert len(rows) == 1
    r = rows[0]
    assert (r["season"], r["gw"], r["player_id"]) == ("2026-27", 2, 480)
    assert r["model_xpts"] == 5.1
    assert r["model_blend_weight"] == 0.5
    assert r["fpl_ep_next"] == 4.5


def test_snapshot_rows_empty_after_deadline():
    now = datetime(2026, 8, 28, 18, 0, tzinfo=timezone.utc)
    assert snapshot_rows(PAYLOAD, now) == []


def test_actuals_rows_shape():
    live = [{"id": 480, "stats": {"total_points": 11, "minutes": 90}}]
    rows = actuals_rows(live, "2026-27", 1, "2026-08-25T10:00:00Z")
    assert rows == [{
        "season": "2026-27", "gw": 1, "player_id": 480,
        "actual_points": 11, "actual_minutes": 90,
        "actuals_captured_at": "2026-08-25T10:00:00Z",
    }]
