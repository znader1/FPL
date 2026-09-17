"""Keeper-specific save volume, replacing the flat saves-per-xGA constant."""
import pandas as pd
import pytest

from src import config, output_model


def _elements(saves_per_90):
    """Three keepers on the same team so the league median is well defined."""
    rows = []
    for i, s90 in enumerate(saves_per_90, start=1):
        row = {"id": i, "team": 10, "element_type": 1}
        if s90 is not None:
            row["saves_per_90"] = s90
        rows.append(row)
    return pd.DataFrame(rows)


def _fixtures():
    return pd.DataFrame([
        {"event": 6, "team_h": 10, "team_a": 20,
         "team_h_difficulty": 3, "team_a_difficulty": 3},
    ])


def _mins(ids):
    return pd.DataFrame([
        {"player_id": i, "exp_minutes": 90.0, "prob_appear": 1.0, "prob_60": 1.0}
        for i in ids
    ]).set_index("player_id")


def _rates(ids, minutes_sample):
    return pd.DataFrame([
        {"player_id": i, "xg90": 0.0, "xa90": 0.0,
         "minutes_sample": float(minutes_sample), "pos": "GKP"}
        for i in ids
    ])


def _run(elements, minutes_sample):
    ids = list(elements["id"])
    return output_model.expected_points(
        elements, _fixtures(), {"_league": 1.4},
        _rates(ids, minutes_sample), _mins(ids), 6)


def test_a_busier_keeper_earns_more_save_points_than_a_quiet_one():
    """Same opponent xGA, different shot-stopping volume."""
    out = _run(_elements([1.5, 3.0, 4.5]), minutes_sample=config.OUTPUT_MIN_MINUTES_TRUST)
    assert out.loc[3, "ep_saves"] > out.loc[2, "ep_saves"] > out.loc[1, "ep_saves"]


def test_low_minutes_keepers_fall_back_to_the_league_prior():
    """With no sample to trust, every keeper gets the same flat estimate."""
    out = _run(_elements([1.5, 3.0, 4.5]), minutes_sample=0.0)
    assert out.loc[1, "ep_saves"] == pytest.approx(out.loc[3, "ep_saves"], abs=1e-9)


def test_ratio_is_clamped_so_one_outlier_cannot_dominate():
    lo, hi = config.OUTPUT_SAVE_RATIO_CLAMP
    out = _run(_elements([3.0, 3.0, 30.0]), minutes_sample=config.OUTPUT_MIN_MINUTES_TRUST)
    assert out.loc[3, "ep_saves"] <= out.loc[1, "ep_saves"] * hi * 1.0001


def test_toggle_off_reproduces_the_flat_constant(monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_APPLY_KEEPER_SAVE_RATE", False)
    out = _run(_elements([1.5, 3.0, 4.5]), minutes_sample=config.OUTPUT_MIN_MINUTES_TRUST)
    assert out.loc[1, "ep_saves"] == pytest.approx(out.loc[3, "ep_saves"], abs=1e-9)


def test_missing_saves_column_is_tolerated():
    out = _run(_elements([None, None, None]), minutes_sample=config.OUTPUT_MIN_MINUTES_TRUST)
    assert out.loc[1, "ep_saves"] > 0


def test_outfield_players_are_unaffected():
    elements = pd.DataFrame([{"id": 1, "team": 10, "element_type": 3, "saves_per_90": 9.0}])
    mins = _mins([1])
    out = output_model.expected_points(
        elements, _fixtures(), {"_league": 1.4}, _rates([1], 300.0), mins, 6)
    assert out.loc[1, "ep_saves"] == pytest.approx(0.0, abs=1e-12)
