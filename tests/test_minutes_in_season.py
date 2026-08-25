import pandas as pd

from src.squad_draft_xg import minutes_from_bootstrap


def _elements():
    return pd.DataFrame(
        [
            # Pre-season carryover shapes: 38-match aggregates.
            {"id": 1, "minutes": 3420, "starts": 38},
            # New first-choice GK: started both GWs since the reset.
            {"id": 2, "minutes": 180, "starts": 2},
            # Benched veteran: no starts yet this season (has history -> sub floor).
            {"id": 3, "minutes": 10, "starts": 0},
            # True unknown: zero minutes AND zero starts.
            {"id": 4, "minutes": 0, "starts": 0},
        ]
    )


def test_preseason_default_keeps_38_match_denominator():
    out = minutes_from_bootstrap(_elements())
    assert out.loc[1, "p_start"] == 1.0
    # 2 starts over a 38-match denominator stays fringe pre-season.
    assert out.loc[2, "p_start"] < 0.1


def test_in_season_denominator_promotes_current_starters():
    out = minutes_from_bootstrap(_elements(), season_matches=2)
    # 2/2 starts with the pseudo-match shrink -> strong but not certain starter.
    assert 0.7 < out.loc[2, "p_start"] < 1.0
    # The ever-present from a 38-start carryover row is capped at 1.0.
    assert out.loc[1, "p_start"] == 1.0


def test_in_season_zero_starts_stays_low_but_keeps_sub_floor():
    out = minutes_from_bootstrap(_elements(), season_matches=2)
    assert out.loc[3, "p_start"] < 0.3
    assert out.loc[3, "prob_appear"] > 0.0  # sub-appearance floor survives
    # No-history guard unchanged: true unknowns stay zeroed.
    assert out.loc[4, "prob_appear"] == 0.0


def test_season_matches_from_fixtures():
    from src.squad_draft_xg import season_matches_from_fixtures

    fx = pd.DataFrame(
        [
            {"event": 1, "finished": True},
            {"event": 1, "finished": True},
            {"event": 2, "finished": True},
            {"event": 2, "finished": False},  # GW2 mid-play -> not counted
            {"event": 3, "finished": False},
        ]
    )
    assert season_matches_from_fixtures(fx) == 1
    # Pre-season: nothing finished -> None keeps carryover behaviour.
    assert season_matches_from_fixtures(fx.assign(finished=False)) is None
    assert season_matches_from_fixtures(pd.DataFrame()) is None
