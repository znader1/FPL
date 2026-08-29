"""Component probabilities surfaced by output_model, and their tie-back to points."""
import numpy as np
import pandas as pd
import pytest

from src import output_model, points_distribution


def _elements():
    return pd.DataFrame([
        {"id": 1, "team": 10, "element_type": 4},   # FWD
        {"id": 2, "team": 10, "element_type": 2},   # DEF
    ])


def _fixtures(events=(6,)):
    return pd.DataFrame([
        {"event": e, "team_h": 10, "team_a": 20,
         "team_h_difficulty": 3, "team_a_difficulty": 3}
        for e in events
    ])


def _mins():
    return pd.DataFrame([
        {"player_id": 1, "exp_minutes": 85.0, "prob_appear": 0.97, "prob_60": 0.88},
        {"player_id": 2, "exp_minutes": 90.0, "prob_appear": 0.95, "prob_60": 0.92},
    ]).set_index("player_id")


def _run(fixtures=None, dc=None):
    return output_model.expected_points(
        _elements(), fixtures if fixtures is not None else _fixtures(),
        {"_league": 1.4}, pd.DataFrame(), _mins(), 6, dc_rates=dc)


def test_component_probabilities_are_present_and_in_range():
    out = _run()
    for col in ["p_goal", "p_assist", "p_clean_sheet", "p_appear", "p_60", "p_dc"]:
        assert col in out.columns, f"{col} missing"
        assert (out[col] >= 0.0).all() and (out[col] <= 1.0).all(), f"{col} out of [0,1]"


def test_p_goal_is_the_poisson_probability_of_at_least_one():
    out = _run()
    row = out.loc[1]
    assert row["p_goal"] == pytest.approx(1.0 - np.exp(-row["exp_goals"]), abs=1e-9)
    assert row["p_assist"] == pytest.approx(1.0 - np.exp(-row["exp_assists"]), abs=1e-9)


def test_component_points_sum_to_expected_points():
    out = _run()
    parts = ["ep_appearance", "ep_goals", "ep_assists", "ep_clean_sheet",
             "ep_conceded", "ep_saves", "ep_bonus", "ep_dc"]
    for pid in out.index:
        assert out.loc[pid, parts].sum() == pytest.approx(out.loc[pid, "exp_points"], abs=1e-9)


def test_double_gameweek_clean_sheet_probability_stays_a_probability():
    """
    Summing per-fixture clean-sheet odds can exceed 1 in a DGW. The expected
    COUNT may exceed 1; the probability must not.
    """
    out = _run(fixtures=_fixtures(events=(6, 6)))
    row = out.loc[2]
    assert row["n_fixtures"] == 2
    assert 0.0 <= row["p_clean_sheet"] <= 1.0
    assert row["exp_clean_sheets"] >= row["p_clean_sheet"]


def test_p_dc_is_gated_by_playing_sixty_minutes():
    dc = pd.DataFrame([{"player_id": 2, "dc_clear_rate": 0.5, "pos": "DEF"}])
    out = _run(dc=dc)
    row = out.loc[2]
    assert row["p_dc"] == pytest.approx(0.5 * row["p_60"], abs=1e-9)


def test_distribution_reproduces_the_models_discrete_mean():
    """
    The card and the optimizer must agree: the distribution's mean plus the
    continuous terms has to land back on the model's own exp_points.
    """
    dc = pd.DataFrame([
        {"player_id": 1, "dc_clear_rate": 0.05, "pos": "FWD"},
        {"player_id": 2, "dc_clear_rate": 0.40, "pos": "DEF"},
    ])
    out = _run(dc=dc)
    for pid in out.index:
        row = out.loc[pid]
        pmf = points_distribution.player_points_pmf(
            pos=row["pos"],
            prob_appear=row["p_appear"], prob_60=row["p_60"],
            exp_goals=row["exp_goals"], exp_assists=row["exp_assists"],
            exp_clean_sheets=row["exp_clean_sheets"],
            n_fixtures=int(row["n_fixtures"]), p_dc=row["p_dc"],
        )
        pmf_mean = float((np.arange(pmf.size) * pmf).sum())
        continuous = row["ep_bonus"] + row["ep_conceded"] + row["ep_saves"]
        assert pmf_mean + continuous == pytest.approx(row["exp_points"], abs=0.01)
