import math

import pandas as pd

from src import config, fixture_difficulty


def _elements():
    # Team 1: elite defense last season (starter GK 15 CS in 33 starts, backup 2 in 5).
    # Team 2: leaky defense (4 CS in 38). Team 3: no GK rows at all.
    return pd.DataFrame(
        [
            {"id": 1, "team": 1, "element_type": 1, "clean_sheets": 15, "starts": 33},
            {"id": 2, "team": 1, "element_type": 1, "clean_sheets": 2, "starts": 5},
            {"id": 3, "team": 2, "element_type": 1, "clean_sheets": 4, "starts": 38},
            {"id": 4, "team": 2, "element_type": 3, "clean_sheets": 9, "starts": 38},  # MID ignored
            {"id": 5, "team": 3, "element_type": 4, "clean_sheets": 0, "starts": 38},
        ]
    )


def _ratings():
    return {
        "_league": 1.4,
        1: {"attack": 1.1, "defense": 1.0},
        2: {"attack": 0.9, "defense": 1.0},
        3: {"attack": 0.8, "defense": 1.2},
    }


def test_cs_prior_tightens_good_defense_and_loosens_bad():
    out = fixture_difficulty.apply_cs_prior(_ratings(), _elements(), weight=0.5)
    # 15 CS/38 implies xGA/match well below league avg -> defense mult drops.
    assert out[1]["defense"] < 1.0
    # 4 CS/38 implies a leaky defense -> defense mult rises.
    assert out[2]["defense"] > 1.0
    # Ordering preserved: better CS record => strictly lower defense multiplier.
    assert out[1]["defense"] < out[2]["defense"]


def test_cs_prior_leaves_attack_league_and_teams_without_gk_untouched():
    ratings = _ratings()
    out = fixture_difficulty.apply_cs_prior(ratings, _elements(), weight=0.5)
    assert out[1]["attack"] == ratings[1]["attack"]
    assert out["_league"] == ratings["_league"]
    assert out[3] == ratings[3]  # no GK row -> unchanged


def test_cs_prior_weight_zero_is_identity():
    ratings = _ratings()
    out = fixture_difficulty.apply_cs_prior(ratings, _elements(), weight=0.0)
    assert out == ratings


def test_cs_prior_handles_missing_column_and_empty_frame():
    ratings = _ratings()
    assert fixture_difficulty.apply_cs_prior(ratings, pd.DataFrame()) == ratings
    no_cs = _elements().drop(columns=["clean_sheets"])
    assert fixture_difficulty.apply_cs_prior(ratings, no_cs) == ratings


def test_cs_prior_result_respects_rating_clamps():
    elements = pd.DataFrame(
        [{"id": 1, "team": 1, "element_type": 1, "clean_sheets": 38, "starts": 38}]
    )
    out = fixture_difficulty.apply_cs_prior(_ratings(), elements, weight=1.0)
    assert out[1]["defense"] >= float(config.FDR_RATING_MIN)
    # Poisson inversion of a perfect CS record must not explode.
    assert math.isfinite(out[1]["defense"])


def test_cs_prior_skips_thin_early_season_samples():
    # Post-GW1 bootstrap: stats reset, one start, one clean sheet. A 1/1 CS
    # record must NOT be treated as signal — ratings stay untouched until the
    # sample reaches FDR_CS_PRIOR_MIN_MATCHES.
    ratings = _ratings()
    elements = pd.DataFrame(
        [
            {"id": 1, "team": 1, "element_type": 1, "clean_sheets": 1, "starts": 1},
            {"id": 3, "team": 2, "element_type": 1, "clean_sheets": 0, "starts": 1},
        ]
    )
    out = fixture_difficulty.apply_cs_prior(ratings, elements, weight=0.5)
    assert out == ratings
