"""Zero-minute GWs in the recent average: an unavailable (injured/suspended)
week is not evidence about a player's level, a fit-but-benched week is."""
import pandas as pd

from src import injury_prior, projections


def _hist(rows):
    return pd.DataFrame(rows, columns=["player_id", "gw", "gw_total_points", "gw_fixture_count", "gw_minutes", "gw_starts"])


def _avg(out, pid):
    return float(out.set_index("player_id").loc[pid, "recent_gw_avg_points"])


def test_zero_gw_dropped_when_status_history_says_unavailable():
    hist = _hist([(1, 3, 6, 1, 90, 1), (1, 4, 6, 1, 90, 1), (1, 5, 0, 1, 0, 0), (1, 6, 6, 1, 90, 1), (1, 7, 6, 1, 90, 1)])
    out = projections.player_recent_gw_map(gw_start=8, window=5, history_df=hist, unavailable={(1, 5)})
    assert _avg(out, 1) == 6.0
    assert int(out.set_index("player_id").loc[1, "recent_gw_samples"]) == 4


def test_zero_gw_kept_for_fit_rotated_player():
    # p2 started 2 of 5 and was fit: the zeros are rotation evidence.
    hist = _hist([(2, 3, 5, 1, 90, 1), (2, 4, 0, 1, 0, 0), (2, 5, 0, 1, 0, 0), (2, 6, 5, 1, 90, 1), (2, 7, 0, 1, 0, 0)])
    out = projections.player_recent_gw_map(gw_start=8, window=5, history_df=hist, unavailable=set())
    assert _avg(out, 2) == 2.0


def test_sandwiched_zero_for_ever_present_starter_is_treated_as_unavailable():
    # No status snapshot for GW7 (pre-dates the status history), but a player
    # who started every other week and blanked once was not benched on merit.
    hist = _hist([(3, 3, 4, 1, 90, 1), (3, 4, 4, 1, 90, 1), (3, 5, 4, 1, 90, 1), (3, 6, 4, 1, 90, 1), (3, 7, 0, 1, 0, 0)])
    out = projections.player_recent_gw_map(gw_start=8, window=5, history_df=hist, unavailable=set())
    assert _avg(out, 3) == 4.0


def test_default_unavailable_is_none_and_zeros_count():
    hist = _hist([(4, 6, 8, 1, 90, 1), (4, 7, 0, 1, 0, 0)])
    out = projections.player_recent_gw_map(gw_start=8, window=5, history_df=hist)
    assert _avg(out, 4) == 4.0


def test_unavailable_gws_from_status_history(tmp_path):
    p = tmp_path / "status_history.csv"
    pd.DataFrame({
        "season": ["2026-27"] * 4, "event": [6, 7, 7, 7], "element": [1, 1, 2, 3],
        "status": ["a", "i", "d", "a"], "chance": [None, 0, 25, None],
    }).to_csv(p, index=False)
    assert injury_prior.unavailable_gws(p) == {(1, 7), (2, 7)}
    assert injury_prior.unavailable_gws(tmp_path / "missing.csv") == set()
