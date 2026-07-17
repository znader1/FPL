import pandas as pd

from src import minutes_model


def _elements(rows):
    return pd.DataFrame(rows)


def test_minutes_projection_exposes_rotation_and_availability():
    # p1: fit nailed starter. p2: fit but historically rotated. p3: injured (25%).
    elements = _elements([
        {"id": 1, "status": "a", "chance_of_playing_next_round": 100},
        {"id": 2, "status": "a", "chance_of_playing_next_round": 100},
        {"id": 3, "status": "d", "chance_of_playing_next_round": 25},
    ])
    # History: p1 always starts, p2 starts half the time, p3 always starts when fit.
    history = pd.DataFrame([
        {"player_id": 1, "gw": 1, "gw_minutes": 90, "gw_starts": 1},
        {"player_id": 1, "gw": 2, "gw_minutes": 90, "gw_starts": 1},
        {"player_id": 2, "gw": 1, "gw_minutes": 90, "gw_starts": 1},
        {"player_id": 2, "gw": 2, "gw_minutes": 0, "gw_starts": 0},
        {"player_id": 3, "gw": 1, "gw_minutes": 90, "gw_starts": 1},
        {"player_id": 3, "gw": 2, "gw_minutes": 90, "gw_starts": 1},
    ])

    out = minutes_model.minutes_projection(elements, history, gw=3)

    assert "rotation_prob_start" in out.columns
    assert "availability" in out.columns
    # Injured player's rotation (history) is high but availability is capped low.
    assert out.loc[3, "rotation_prob_start"] > 0.6
    assert out.loc[3, "availability"] <= 0.25 + 1e-9
    # prob_start folds availability in, so it is <= rotation for the injured player.
    assert out.loc[3, "prob_start"] <= out.loc[3, "rotation_prob_start"] + 1e-9
    # Fit nailed starter: rotation high, availability 1.0.
    assert out.loc[1, "rotation_prob_start"] > out.loc[2, "rotation_prob_start"]
    assert out.loc[1, "availability"] == 1.0


def test_rotation_minutes_multiplier_values():
    m = minutes_model.rotation_minutes_multiplier

    # Nailed starter -> capped at 1.0.
    assert abs(float(m(0.95, 0.99).iloc[0]) - 1.0) < 1e-9
    # Rotation risk (0.55 start / 0.80 appear): 0.55/0.85 + 0.30*0.25 = 0.7221.
    assert abs(float(m(0.55, 0.80).iloc[0]) - 0.72205882) < 1e-6
    # Injured (0.10 start / 0.20 appear): 0.10/0.85 + 0.30*0.10 = 0.14765.
    assert abs(float(m(0.10, 0.20).iloc[0]) - 0.14764706) < 1e-6
    # Missing data -> no discount.
    assert float(m(float("nan"), float("nan")).iloc[0]) == 1.0


def test_rotation_minutes_multiplier_is_monotonic_and_clamped():
    m = minutes_model.rotation_minutes_multiplier
    vals = [float(m(x).iloc[0]) for x in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]]
    assert vals == sorted(vals)          # non-decreasing in prob_start
    assert all(0.0 <= v <= 1.0 for v in vals)
    assert vals[0] == 0.0 and vals[-1] == 1.0


def test_rotation_minutes_multiplier_preserves_series_index_positionally():
    import pandas as pd
    ps = pd.Series([0.95, 0.55, 0.10], index=[201, 202, 203])
    out = minutes_model.rotation_minutes_multiplier(ps, 0.9)
    assert list(out.index) == [201, 202, 203]
    assert not out.isna().any()
    expected_202 = min(0.55 / 0.85, 1.0) + max(0.9 - 0.55, 0.0) * 0.30
    assert abs(float(out.loc[202]) - expected_202) < 1e-9


def test_rotation_minutes_multiplier_aligns_mismatched_index_by_position():
    import pandas as pd
    ps = pd.Series([0.95, 0.55, 0.10], index=[201, 202, 203])
    pa = pd.Series([0.99, 0.80, 0.20], index=[7, 8, 9])  # different index on purpose
    out = minutes_model.rotation_minutes_multiplier(ps, pa)
    assert list(out.index) == [201, 202, 203]
    assert not out.isna().any()
    # positional: ps[202]=0.55 pairs with pa[8]=0.80
    expected_202 = min(0.55 / 0.85, 1.0) + max(0.80 - 0.55, 0.0) * 0.30
    assert abs(float(out.loc[202]) - expected_202) < 1e-9
