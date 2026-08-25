import pandas as pd
import pytest

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


def test_rotation_minutes_multiplier_ragged_prob_appear_raises():
    # len(prob_appear) is neither 1 nor len(prob_start_eff) -> positional arithmetic
    # would silently reintroduce NaN via misaligned .where(); must raise instead.
    with pytest.raises(ValueError):
        minutes_model.rotation_minutes_multiplier([0.95, 0.55, 0.10], [0.99, 0.80])


def test_rotation_minutes_multiplier_equal_length_and_scalar_broadcast_still_work():
    m = minutes_model.rotation_minutes_multiplier
    # Equal-length prob_appear (len(pa) == len(ps)): unaffected by the new guard.
    out_equal = m([0.95, 0.55], [0.99, 0.80])
    assert len(out_equal) == 2
    assert not out_equal.isna().any()
    # Length-1 prob_appear broadcast against a longer prob_start_eff: unaffected.
    out_broadcast = m([0.95, 0.55, 0.10], 0.9)
    assert len(out_broadcast) == 3
    assert not out_broadcast.isna().any()


def test_compute_gw_minutes_multiplier_fades_injury_not_rotation():
    # id 10: fit rotation risk (avail 1.0). id 20: injured (avail 0.25, fit history).
    mins_df = pd.DataFrame(
        {
            "prob_start": [0.55, 0.225],
            "prob_appear": [0.80, 0.30],
            "prob_60": [0.47, 0.19],
            "exp_minutes": [55.0, 20.0],
            "rotation_prob_start": [0.55, 0.90],
            "availability": [1.0, 0.25],
        },
        index=[10, 20],
    )

    now = minutes_model.compute_gw_minutes_multiplier(mins_df, [10, 20], gw_offset=0)
    later = minutes_model.compute_gw_minutes_multiplier(mins_df, [10, 20], gw_offset=1)

    # Rotation risk: availability is 1.0, so future fade changes nothing.
    assert abs(float(now.iloc[0]) - float(later.iloc[0])) < 1e-9
    # Injured player: future GW is discounted LESS (injury assumed to resolve).
    assert float(later.iloc[1]) > float(now.iloc[1])
    # Missing id -> no discount.
    missing = minutes_model.compute_gw_minutes_multiplier(mins_df, [999], gw_offset=0)
    assert float(missing.iloc[0]) == 1.0


def test_compute_gw_minutes_multiplier_empty_or_none_mins_df_is_all_ones():
    empty_result = minutes_model.compute_gw_minutes_multiplier(pd.DataFrame(), [1, 2, 3], gw_offset=0)
    none_result = minutes_model.compute_gw_minutes_multiplier(None, [1, 2, 3], gw_offset=0)

    for result in (empty_result, none_result):
        assert len(result) == 3
        assert (result == 1.0).all()
