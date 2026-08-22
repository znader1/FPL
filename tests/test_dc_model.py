"""Tests for the defensive-contribution scoring term in output_model."""
import pandas as pd

from src import output_model, config


def _history(rows):
    return pd.DataFrame(rows)


def test_dc_rate_is_fraction_of_60min_games_clearing_threshold():
    # A DEF (threshold 10) who cleared in 3 of 4 started games.
    hist = _history([
        {"element": 1, "element_type": 2, "minutes": 90, "defensive_contribution": dc, "event": gw}
        for gw, dc in zip(range(1, 5), [12, 11, 8, 15])
    ])
    rates = output_model.compute_dc_rates(hist, gw=6)
    row = rates[rates["player_id"] == 1].iloc[0]
    assert row["pos"] == "DEF"
    # 3/4 cleared, shrunk toward the DEF base rate (0.12) by 4/6 confidence.
    conf = 4 / config.OUTPUT_DC_MIN_GAMES_TRUST
    expected = conf * 0.75 + (1 - conf) * config.OUTPUT_DC_BASE_RATE["DEF"]
    assert abs(row["dc_clear_rate"] - expected) < 1e-6


def test_cameo_games_excluded_from_rate():
    # Two 90-min games (both clear) plus two cameos that couldn't clear —
    # the cameos must not drag the rate down.
    hist = _history([
        {"element": 2, "element_type": 2, "minutes": 90, "defensive_contribution": 14, "event": 1},
        {"element": 2, "element_type": 2, "minutes": 90, "defensive_contribution": 14, "event": 2},
        {"element": 2, "element_type": 2, "minutes": 20, "defensive_contribution": 2, "event": 3},
        {"element": 2, "element_type": 2, "minutes": 15, "defensive_contribution": 1, "event": 4},
    ])
    rates = output_model.compute_dc_rates(hist, gw=6)
    row = rates[rates["player_id"] == 2].iloc[0]
    conf = 2 / config.OUTPUT_DC_MIN_GAMES_TRUST
    expected = conf * 1.0 + (1 - conf) * config.OUTPUT_DC_BASE_RATE["DEF"]
    assert abs(row["dc_clear_rate"] - expected) < 1e-6


def test_no_future_leak():
    hist = _history([
        {"element": 3, "element_type": 3, "minutes": 90, "defensive_contribution": 20, "event": 7},
    ])
    # gw=6 must not see the GW7 game.
    assert output_model.compute_dc_rates(hist, gw=6).empty


def test_missing_column_returns_empty():
    hist = _history([{"element": 4, "element_type": 2, "minutes": 90, "event": 1}])
    assert output_model.compute_dc_rates(hist, gw=6).empty


def test_dc_adds_points_and_is_gated_by_prob60():
    elements = pd.DataFrame([{"id": 1, "team": 10, "element_type": 2}])
    fixtures = pd.DataFrame([
        {"event": 6, "team_h": 10, "team_a": 20, "team_h_difficulty": 3, "team_a_difficulty": 3},
    ])
    ratings = {"_league": 1.4}
    mins = pd.DataFrame([{"player_id": 1, "exp_minutes": 90.0, "prob_appear": 1.0, "prob_60": 1.0}]).set_index("player_id")
    dc = pd.DataFrame([{"player_id": 1, "dc_clear_rate": 0.5, "pos": "DEF"}])

    with_dc = output_model.expected_points(elements, fixtures, ratings, pd.DataFrame(), mins, 6, dc_rates=dc)
    without = output_model.expected_points(elements, fixtures, ratings, pd.DataFrame(), mins, 6, dc_rates=None)

    # 0.5 clear-rate * 2 points * prob_60 1.0 = +1.0 exp point, in ep_dc only.
    assert abs(with_dc.loc[1, "ep_dc"] - 1.0) < 1e-6
    assert abs(without.loc[1, "ep_dc"] - 0.0) < 1e-6
    assert abs((with_dc.loc[1, "exp_points"] - without.loc[1, "exp_points"]) - 1.0) < 1e-6


def test_dc_toggle_off_zeroes_the_term(monkeypatch):
    elements = pd.DataFrame([{"id": 1, "team": 10, "element_type": 2}])
    fixtures = pd.DataFrame([
        {"event": 6, "team_h": 10, "team_a": 20, "team_h_difficulty": 3, "team_a_difficulty": 3},
    ])
    mins = pd.DataFrame([{"player_id": 1, "exp_minutes": 90.0, "prob_appear": 1.0, "prob_60": 1.0}]).set_index("player_id")
    dc = pd.DataFrame([{"player_id": 1, "dc_clear_rate": 0.9, "pos": "DEF"}])
    monkeypatch.setattr(config, "OUTPUT_APPLY_DC", False)
    out = output_model.expected_points(elements, fixtures, {"_league": 1.4}, pd.DataFrame(), mins, 6, dc_rates=dc)
    assert abs(out.loc[1, "ep_dc"]) < 1e-9
