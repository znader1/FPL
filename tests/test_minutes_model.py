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
