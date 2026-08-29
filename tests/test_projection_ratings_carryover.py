"""
The projection path must use carryover-seeded team ratings.

With one gameweek played, raw current-season ratings come off a single match per
team: one 4-0 win makes a side look world-beating and inflates every player on
it. It also made projections disagree with /fixtures/difficulty, which has always
used resolve_team_ratings.
"""
import json

import pandas as pd
import pytest

from src import expected_points, fixture_difficulty


TEAMS = {1: "AAA", 2: "BBB"}


def _seed_file(tmp_path):
    # AAA rated strong going in, BBB weak.
    # The loader reads a "teams" wrapper, keyed by short name.
    seed = {"teams": {
        "AAA": {"attack": 1.45, "defense": 0.70},
        "BBB": {"attack": 0.70, "defense": 1.45},
    }}
    fp = tmp_path / "seed.json"
    fp.write_text(json.dumps(seed))
    return str(fp)


def _one_match_history():
    """A single freak result: BBB hammers AAA on xG."""
    return pd.DataFrame([
        {"fixture": 1, "element": 10, "team_id": 1, "opponent_team": 2, "event": 1,
         "was_home": True, "minutes": 90, "expected_goals": 0.1, "expected_assists": 0.0,
         "kickoff_time": "2026-08-21T17:30:00Z"},
        {"fixture": 1, "element": 20, "team_id": 2, "opponent_team": 1, "event": 1,
         "was_home": False, "minutes": 90, "expected_goals": 4.0, "expected_assists": 0.0,
         "kickoff_time": "2026-08-21T17:30:00Z"},
    ])


def test_one_freak_match_does_not_overturn_the_prior(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture_difficulty.config, "FDR_RATINGS_SEED_PATH", _seed_file(tmp_path))
    team_match_xg = fixture_difficulty.build_team_match_xg(_one_match_history())

    live_only = fixture_difficulty.compute_team_ratings(team_match_xg)
    seeded = fixture_difficulty.resolve_team_ratings(team_match_xg, teams_short_map=TEAMS)

    # Live-only lets the single match decide: BBB looks like the better attack.
    assert live_only[2]["attack"] > live_only[1]["attack"]
    # Seeded still favours AAA, whose prior says otherwise, on one match of evidence.
    assert seeded[1]["attack"] > seeded[2]["attack"]
    assert seeded[1]["source"] in {"blend", "carryover"}


def test_build_ratings_uses_the_carryover_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture_difficulty.config, "FDR_RATINGS_SEED_PATH", _seed_file(tmp_path))
    ratings = expected_points.build_ratings(
        match_df=_one_match_history(), teams_short_map=TEAMS, knowledge_path=str(tmp_path / "none.json")
    )
    # A "source" key only exists on the carryover path.
    assert ratings[1].get("source") in {"blend", "carryover", "live"}


def test_falls_back_to_live_only_without_a_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        fixture_difficulty.config, "FDR_RATINGS_SEED_PATH", str(tmp_path / "missing.json"))
    team_match_xg = fixture_difficulty.build_team_match_xg(_one_match_history())
    seeded = fixture_difficulty.resolve_team_ratings(team_match_xg, teams_short_map=TEAMS)
    live_only = fixture_difficulty.compute_team_ratings(team_match_xg)
    # No seed on disk -> identical behaviour, so the change is safe where no seed ships.
    assert seeded[2]["attack"] == pytest.approx(live_only[2]["attack"], abs=1e-9)


def test_promoted_teams_get_the_weak_default_not_a_league_average(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture_difficulty.config, "FDR_RATINGS_SEED_PATH", _seed_file(tmp_path))
    teams = dict(TEAMS)
    teams[3] = "NEW"  # promoted, absent from the seed
    ratings = fixture_difficulty.resolve_team_ratings(
        fixture_difficulty.build_team_match_xg(_one_match_history()), teams_short_map=teams)
    assert ratings[3]["source"] == "promoted"
    assert ratings[3]["defense"] > 1.0  # concedes more than average
