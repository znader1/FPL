from datetime import datetime, timezone

from scripts.chip_snapshot_to_db import chip_plan_rows, chip_actuals_rows

PLAN_PAYLOAD = {
    "season": "2026-27", "next_gw": 4, "deadline_utc": "2026-09-12T17:30:00Z",
    "entry_id": 123,
    "plan": {
        "current_gw": 4,
        "chips_remaining": [{"name": "wildcard", "available": True, "half": 1, "expires_gw": 19}],
        "horizon_model_gws": 8,
        "recommendations": [{"chip": "wildcard", "event_id": 8, "ev_gain": 9.1,
                             "provisional": False, "reasons": [], "ev_curve": [{"gw": 4, "ev": 2.0}]}],
        "nudge": None,
        "transfer_context": {"planned_transfers_net_gain": 3.0, "wc_alternative_gw": 8},
    },
    "model_meta": {"horizon": 8, "min_ev": {"wildcard": 6.0}},
}


def test_chip_plan_rows_before_deadline():
    now = datetime(2026, 9, 12, 16, 0, tzinfo=timezone.utc)
    rows = chip_plan_rows(PLAN_PAYLOAD, now)
    assert len(rows) == 1
    r = rows[0]
    assert (r["season"], r["gw"], r["entry_id"]) == ("2026-27", 4, 123)
    assert r["recommendations"][0]["chip"] == "wildcard"
    assert r["ev_curves"] == {"wildcard": [{"gw": 4, "ev": 2.0}]}
    assert r["model_meta"]["horizon"] == 8


def test_chip_plan_rows_empty_after_deadline():
    now = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)
    assert chip_plan_rows(PLAN_PAYLOAD, now) == []


def test_chip_actuals_rows_bench_and_captain():
    chips_played = [{"name": "bboost", "event": 4}]
    picks = [{"element": i, "position": i, "is_captain": i == 1} for i in range(1, 16)]
    live_points = {i: 2 for i in range(1, 16)}
    live_points[1] = 10  # captain hauled
    rows = chip_actuals_rows(
        entry_id=123, season="2026-27", gw=4, chips_played=chips_played,
        picks=picks, live_points_by_id=live_points, now_iso="2026-09-15T09:00:00+00:00",
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["chip_played"] == "bench_boost"          # normalized to canonical
    # bench = positions 12-15 → 4 players x 2 pts
    assert r["realized_chip_ev"]["bench_boost"] == 8
    # TC realized = captain's actual points (the extra x1)
    assert r["realized_chip_ev"]["triple_captain"] == 10
