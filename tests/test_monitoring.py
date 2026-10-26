import pandas as pd

from src.monitoring import frames_from_snapshots, rollback_verdict


def _frames(errors_by_gw, bias_cells=None):
    """One frame per GW; every row has |xpts - actual| == err."""
    frames = []
    for gw, err in errors_by_gw.items():
        rows = [{"player_id": i, "position": "DEF", "price_m": 4.5, "xpts": 2.0 + err,
                 "actual": 2.0, "minutes": 90, "had_fixture": True, "gw": gw} for i in range(25)]
        frames.append(pd.DataFrame(rows))
    return frames


def test_wait_until_three_gws():
    assert rollback_verdict(_frames({9: 1.0}), _frames({9: 0.1}), 2) == "wait"


def test_rollback_when_shadow_mae_clearly_lower():
    live = _frames({9: 1.000, 10: 1.000, 11: 1.000})
    shadow = _frames({9: 0.985, 10: 0.985, 11: 0.985})   # 1.5% lower
    assert rollback_verdict(live, shadow, 3) == "rollback"


def test_keep_when_shadow_only_slightly_better_and_bias_not_better():
    live = _frames({9: 1.000, 10: 1.000, 11: 1.000})
    shadow = _frames({9: 0.996, 10: 0.996, 11: 0.996})   # 0.4% lower, but |bias| 0.996 < 1.0
    # Same-sign bias: shadow's band bias (0.996) is smaller, so the bias rule fires.
    assert rollback_verdict(live, shadow, 3) == "rollback"
    worse_shadow = _frames({9: 1.004, 10: 1.004, 11: 1.004})
    assert rollback_verdict(live, worse_shadow, 3) == "keep"


def test_frames_from_snapshots_uses_the_named_column_and_skips_unfinished_gws():
    rows = pd.DataFrame([
        {"gw": 9, "player_id": 1, "pos": "MID", "price_m": 9.8, "model_xpts": 4.0,
         "runner_xpts": 4.1, "shadow_xpts": 3.5, "actual_points": 2, "actual_minutes": 90},
        {"gw": 9, "player_id": 2, "pos": "DEF", "price_m": 4.5, "model_xpts": 0.2,
         "runner_xpts": 0.2, "shadow_xpts": 0.2, "actual_points": 0, "actual_minutes": 0},
        {"gw": 10, "player_id": 1, "pos": "MID", "price_m": 9.8, "model_xpts": 4.0,
         "runner_xpts": 4.0, "shadow_xpts": 3.0, "actual_points": None, "actual_minutes": None},
    ])
    frames = frames_from_snapshots(rows, "shadow_xpts")
    assert len(frames) == 1
    f = frames[0].set_index("player_id")
    assert f.loc[1, "xpts"] == 3.5 and f.loc[1, "actual"] == 2
    assert bool(f.loc[1, "had_fixture"]) is True
    assert bool(f.loc[2, "had_fixture"]) is False   # 0 minutes and model said ~0: no fixture assumed


def test_history_defines_the_fixture_population():
    rows = pd.DataFrame([
        {"gw": 9, "player_id": 2, "pos": "DEF", "price_m": 4.5, "model_xpts": 0.2,
         "actual_points": 0, "actual_minutes": 0},
    ])
    hist = pd.DataFrame([{"gw": 9, "player_id": 2, "gw_fixture_count": 1}])
    f = frames_from_snapshots(rows, "model_xpts", hist)[0]
    assert bool(f["had_fixture"].iloc[0]) is True   # benched, but his team played: counted
