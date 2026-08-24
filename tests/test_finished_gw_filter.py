import pandas as pd
from src import projections


def _hist(rows):
    # NOTE: player_recent_gw_map's groupby().agg() requires gw_fixture_count
    # to be present (it is always populated by the real history loader); the
    # brief's 5-col fixture is adapted here to include it so the aggregation
    # doesn't KeyError, while keeping the asserted semantics identical to the
    # brief (cutoff excludes in-play GW; no cutoff keeps current behaviour).
    return pd.DataFrame(
        rows,
        columns=["player_id", "gw", "gw_total_points", "gw_fixture_count", "gw_minutes", "gw_starts"],
    )


def test_in_play_gw_excluded_when_cutoff_set():
    hist = _hist([
        (1, 8, 10.0, 1, 90, 1),
        (1, 9, 2.0, 1, 45, 1),   # in-play GW9 partial data
    ])
    # gw_start=10 (planning next GW), GW9 unfinished -> cutoff 8
    out = projections.player_recent_gw_map(gw_start=10, window=5, history_df=hist, finished_gw_max=8)
    row = out[out["player_id"] == 1].iloc[0]
    assert row["recent_history_max_gw"] == 8
    assert row["recent_gw_avg_points"] == 10.0   # GW9 row dropped


def test_no_cutoff_keeps_current_behaviour():
    hist = _hist([(1, 8, 10.0, 1, 90, 1), (1, 9, 2.0, 1, 45, 1)])
    out = projections.player_recent_gw_map(gw_start=10, window=5, history_df=hist)
    row = out[out["player_id"] == 1].iloc[0]
    assert row["recent_history_max_gw"] == 9
    assert row["recent_gw_avg_points"] == 6.0
