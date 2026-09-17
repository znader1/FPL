"""
Guards on the cost of a model build.

/squad now triggers a projection so a future gameweek shows a number instead of
a dash, which put this path on every squad load. These pin the shortcuts that
keep it affordable — none of them may change the result.
"""
import pandas as pd
import pytest

from src import expected_points, fixture_difficulty, minutes_model, output_model


def _history(events=(1, 2)):
    rows = []
    for gw in events:
        for pid in (10, 20):
            rows.append({
                "element": pid, "element_type": 3 if pid == 10 else 2,
                "team_id": 1 if pid == 10 else 2, "fixture": 100 + gw, "event": gw,
                "was_home": pid == 10, "kickoff_time": f"2026-08-2{gw}T17:30:00Z",
                "minutes": 90, "expected_goals": 0.4, "expected_assists": 0.2,
                "defensive_contribution": 8, "expected_goals_conceded": 1.0,
                "saves": 0, "total_points": 5, "bps": 20, "starts": 1,
            })
    return pd.DataFrame(rows)


ELEMENTS = pd.DataFrame([
    {"id": 10, "team": 1, "element_type": 3, "status": "a",
     "chance_of_playing_next_round": None, "chance_of_playing_this_round": None},
    {"id": 20, "team": 2, "element_type": 2, "status": "a",
     "chance_of_playing_next_round": None, "chance_of_playing_this_round": None},
])

FIXTURES = pd.DataFrame([
    {"id": 100 + gw, "event": gw, "team_h": 1, "team_a": 2,
     "team_h_difficulty": 3, "team_a_difficulty": 3,
     "kickoff_time": f"2026-08-2{gw}T17:30:00Z"}
    for gw in (1, 2, 3, 4, 5)
])


def test_rate_builders_run_once_for_gameweeks_beyond_the_history(monkeypatch):
    """
    Both filter history to `event < gw`, so every gameweek at or past the last
    one on file sees identical input. Over a horizon that was the same work
    repeated per gameweek.
    """
    calls = []
    real_rates = output_model.compute_player_rates
    monkeypatch.setattr(output_model, "compute_player_rates",
                        lambda df, gw, **kw: (calls.append(gw) or real_rates(df, gw, **kw)))

    expected_points.build_expected_points(
        ELEMENTS, FIXTURES, {1: "AAA", 2: "BBB"}, gw_start=3, horizon_gws=3,
        match_df=_history(), minutes_history=pd.DataFrame())

    assert calls == [3], f"expected one rate build for GW3-5, got {calls}"


def test_gameweeks_inside_the_history_are_not_collapsed(monkeypatch):
    """A backtest projecting GW2 and GW3 must see different history for each."""
    calls = []
    real_rates = output_model.compute_player_rates
    monkeypatch.setattr(output_model, "compute_player_rates",
                        lambda df, gw, **kw: (calls.append(gw) or real_rates(df, gw, **kw)))

    expected_points.build_expected_points(
        ELEMENTS, FIXTURES, {1: "AAA", 2: "BBB"}, gw_start=2, horizon_gws=2,
        match_df=_history(events=(1, 2, 3)), minutes_history=pd.DataFrame())

    assert calls == [2, 3], f"distinct history windows must not share a build: {calls}"


def test_minutes_are_never_collapsed(monkeypatch):
    """Minutes decay is measured from the gameweek projected, so each differs."""
    calls = []
    real = minutes_model.minutes_projection
    monkeypatch.setattr(minutes_model, "minutes_projection",
                        lambda el, hist, gw: (calls.append(gw) or real(el, hist, gw)))

    expected_points.build_expected_points(
        ELEMENTS, FIXTURES, {1: "AAA", 2: "BBB"}, gw_start=3, horizon_gws=3,
        match_df=_history(), minutes_history=pd.DataFrame())

    assert calls == [3, 4, 5]


def test_history_files_are_re_read_when_they_change(tmp_path):
    """The refresh rewrites these files; a cache that served stale rows would
    silently freeze the model at whatever it first loaded."""
    d = tmp_path / "2026-27"
    d.mkdir(parents=True)
    fp = d / "player_match_history_2026-27.csv"

    _history(events=(1,)).to_csv(fp, index=False)
    first = fixture_difficulty.load_match_history(base_dir=str(tmp_path))
    assert sorted(first["event"].unique()) == [1]

    _history(events=(1, 2)).to_csv(fp, index=False)
    second = fixture_difficulty.load_match_history(base_dir=str(tmp_path))
    assert sorted(second["event"].unique()) == [1, 2], "a rewritten file must not be served from cache"


def test_non_playing_elements_get_a_zero_distribution_without_convolving():
    """Roughly two thirds of elements have no realistic appearance."""
    ep = pd.DataFrame([
        {"id": 10, "pos": "MID", "exp_points": 0.0, "p_appear": 0.0, "p_60": 0.0,
         "exp_goals": 0.0, "exp_assists": 0.0, "exp_clean_sheets": 0.0,
         "n_fixtures": 1, "p_dc": 0.0},
    ]).set_index("id")
    out = expected_points._attach_components(pd.DataFrame({"id": [10]}), ep)
    assert out.loc[0, "modal_points"] == 0
    assert out.loc[0, "p_return_6"] == 0.0
    assert out.loc[0, "p_haul_10"] == 0.0
