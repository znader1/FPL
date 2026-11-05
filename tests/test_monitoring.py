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


def test_uniform_errors_roll_back_only_beyond_the_margins():
    live = _frames({9: 1.000, 10: 1.000, 11: 1.000})
    assert rollback_verdict(live, _frames({9: 0.996, 10: 0.996, 11: 0.996}), 3) == "keep"      # 0.4%: noise
    assert rollback_verdict(live, _frames({9: 1.004, 10: 1.004, 11: 1.004}), 3) == "keep"
    assert rollback_verdict(live, _frames({9: 0.985, 10: 0.985, 11: 0.985}), 3) == "rollback"  # 1.5%


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


def _mixed(err_pos, err_neg, gw):
    """Half the rows over-predict by err_pos, half under-predict by err_neg:
    MAE and |bias| move independently."""
    rows = [{"player_id": i, "position": "DEF", "price_m": 4.5, "xpts": 2.0 + err_pos, "actual": 2.0,
             "minutes": 90, "had_fixture": True, "gw": gw} for i in range(25)]
    rows += [{"player_id": 100 + i, "position": "DEF", "price_m": 4.5, "xpts": 2.0 - err_neg, "actual": 2.0,
              "minutes": 90, "had_fixture": True, "gw": gw} for i in range(25)]
    return pd.DataFrame(rows)


def test_keep_when_shadow_mae_only_slightly_lower_and_bias_not_better():
    live = [_mixed(1.0, 0.8, g) for g in (9, 10, 11)]      # MAE 0.9, bias +0.1
    shadow = [_mixed(1.3, 0.492, g) for g in (9, 10, 11)]  # MAE 0.896 (0.4% lower), bias +0.404
    assert rollback_verdict(live, shadow, 3) == "keep"


def test_bias_noise_inside_the_margin_does_not_roll_back():
    live = [_mixed(1.0, 0.8, g) for g in (9, 10, 11)]      # bias +0.100
    shadow = [_mixed(1.0, 0.8018, g) for g in (9, 10, 11)]  # bias +0.0991: 0.9% better, MAE ~equal
    assert rollback_verdict(live, shadow, 3) == "keep"


def test_shadow_verdicts_group_by_previous_version():
    from src.monitoring import shadow_verdicts
    rows = []
    for ver, err in (("v1", 0.5), ("v2", 2.0)):
        for gw in (9, 10, 11):
            for i in range(25):
                rows.append({"gw": gw, "player_id": i, "pos": "DEF", "price_m": 4.5, "model_xpts": 2.0,
                             "runner_xpts": 2.0 + 1.0, "shadow_xpts": 2.0 + err,
                             "shadow_model_version": ver, "actual_points": 2, "actual_minutes": 90})
    out = shadow_verdicts(pd.DataFrame(rows))
    assert set(out) == {"v1", "v2"}
    assert out["v1"]["verdict"] == "rollback"   # previous model v1 was clearly better
    assert out["v2"]["verdict"] == "keep"
