"""Set-piece duty uplift in the xG component model."""
import pandas as pd
import pytest

from src import config, output_model


def _elements(**over):
    base = {"id": 1, "team": 10, "element_type": 3,
            "penalties_order": None,
            "direct_freekicks_order": None,
            "corners_and_indirect_freekicks_order": None}
    base.update(over)
    return pd.DataFrame([base])


def _fixtures():
    return pd.DataFrame([
        {"event": 6, "team_h": 10, "team_a": 20,
         "team_h_difficulty": 3, "team_a_difficulty": 3},
    ])


def _mins():
    return pd.DataFrame([
        {"player_id": 1, "exp_minutes": 90.0, "prob_appear": 1.0, "prob_60": 1.0},
    ]).set_index("player_id")


def _rates(minutes_sample):
    """A player rate row with a chosen minutes sample, so the taper is controllable."""
    return pd.DataFrame([{
        "player_id": 1, "xg90": 0.20, "xa90": 0.15,
        "minutes_sample": float(minutes_sample), "pos": "MID",
    }])


def _run(elements, rates):
    return output_model.expected_points(
        elements, _fixtures(), {"_league": 1.4}, rates, _mins(), 6)


def test_penalty_taker_projects_above_an_identical_non_taker():
    rates = _rates(minutes_sample=0.0)   # no own history -> full uplift
    taker = _run(_elements(penalties_order=1), rates)
    other = _run(_elements(penalties_order=None), rates)
    assert taker.loc[1, "exp_goals"] > other.loc[1, "exp_goals"]
    assert taker.loc[1, "exp_points"] > other.loc[1, "exp_points"]


def test_second_choice_taker_gets_no_uplift():
    rates = _rates(minutes_sample=0.0)
    second = _run(_elements(penalties_order=2), rates)
    none = _run(_elements(penalties_order=None), rates)
    assert second.loc[1, "exp_goals"] == pytest.approx(none.loc[1, "exp_goals"], abs=1e-12)


def test_uplift_tapers_away_once_the_player_has_their_own_sample():
    """
    A taker's own expected_goals history already contains their penalties.
    Applying the full uplift on top would count them twice.
    """
    full_sample = config.OUTPUT_MIN_MINUTES_TRUST
    established = _run(_elements(penalties_order=1), _rates(minutes_sample=full_sample))
    baseline = _run(_elements(penalties_order=None), _rates(minutes_sample=full_sample))
    assert established.loc[1, "exp_goals"] == pytest.approx(
        baseline.loc[1, "exp_goals"], abs=1e-12)

    # Half the trust threshold -> half the uplift.
    half = _run(_elements(penalties_order=1), _rates(minutes_sample=full_sample / 2))
    assert baseline.loc[1, "exp_goals"] < half.loc[1, "exp_goals"]
    assert half.loc[1, "exp_goals"] < _run(
        _elements(penalties_order=1), _rates(minutes_sample=0.0)).loc[1, "exp_goals"]


def test_corner_taker_gets_an_assist_uplift_not_a_goal_uplift():
    rates = _rates(minutes_sample=0.0)
    corners = _run(_elements(corners_and_indirect_freekicks_order=1), rates)
    none = _run(_elements(), rates)
    assert corners.loc[1, "exp_assists"] > none.loc[1, "exp_assists"]
    assert corners.loc[1, "exp_goals"] == pytest.approx(none.loc[1, "exp_goals"], abs=1e-12)


def test_freekick_taker_gets_a_goal_uplift():
    rates = _rates(minutes_sample=0.0)
    fk = _run(_elements(direct_freekicks_order=1), rates)
    none = _run(_elements(), rates)
    assert fk.loc[1, "exp_goals"] > none.loc[1, "exp_goals"]


def test_toggle_off_reproduces_the_previous_output_exactly(monkeypatch):
    rates = _rates(minutes_sample=0.0)
    monkeypatch.setattr(config, "OUTPUT_APPLY_SETPIECE", False)
    taker = _run(_elements(penalties_order=1), rates)
    none = _run(_elements(), rates)
    assert taker.loc[1, "exp_points"] == pytest.approx(none.loc[1, "exp_points"], abs=1e-12)


def test_missing_setpiece_columns_are_tolerated():
    # Bootstrap frames built from an older snapshot may not carry the columns.
    elements = pd.DataFrame([{"id": 1, "team": 10, "element_type": 3}])
    out = _run(elements, _rates(minutes_sample=0.0))
    assert out.loc[1, "exp_points"] > 0
