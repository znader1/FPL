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


def _hist_with_team(rows):
    # The blank-GW fixture-backfill branch in player_recent_gw_map only
    # activates when history rows carry gw_team_id_end (used to look up the
    # player's team and cross-reference it against scheduled fixtures).
    return pd.DataFrame(
        rows,
        columns=[
            "player_id", "gw", "gw_total_points", "gw_fixture_count",
            "gw_minutes", "gw_starts", "gw_team_id_end",
        ],
    )


def _fixtures(rows):
    return pd.DataFrame(rows, columns=["event", "team_h", "team_a"])


def test_in_play_gw_not_backfilled_as_zero_when_cutoff_set():
    # Regression test: the blank-GW backfill grid used to span
    # [window_start, gw_start) independent of finished_gw_max. Since the
    # cutoff removes the GW9 row from the aggregation frame but team 100 has
    # a *scheduled* fixture in GW9 (in-play, not finished), the backfill used
    # to treat the missing row as a blank GW and re-insert it as a
    # fabricated 0-point sample -- silently undoing the cutoff.
    hist = _hist_with_team([
        (1, 8, 10.0, 1, 90, 1, 100),
        (1, 9, 2.0, 1, 45, 1, 100),  # in-play GW9, must be fully excluded
    ])
    fixtures = _fixtures([
        (8, 100, 200),
        (9, 100, 200),  # team 100's GW9 fixture is scheduled (in-play)
    ])
    out = projections.player_recent_gw_map(
        gw_start=10, window=5, history_df=hist, fixtures=fixtures, finished_gw_max=8,
    )
    row = out[out["player_id"] == 1].iloc[0]
    assert row["recent_history_max_gw"] == 8
    assert row["recent_gw_samples"] == 1
    assert row["recent_gw_avg_points"] == 10.0  # not resurrected as a 0.0 backfill row


def test_no_cutoff_keeps_current_backfill_behaviour_with_fixtures():
    hist = _hist_with_team([
        (1, 8, 10.0, 1, 90, 1, 100),
        (1, 9, 2.0, 1, 45, 1, 100),
    ])
    fixtures = _fixtures([
        (8, 100, 200),
        (9, 100, 200),
    ])
    out = projections.player_recent_gw_map(
        gw_start=10, window=5, history_df=hist, fixtures=fixtures,
    )
    row = out[out["player_id"] == 1].iloc[0]
    assert row["recent_history_max_gw"] == 9
    assert row["recent_gw_samples"] == 2
    assert row["recent_gw_avg_points"] == 6.0
