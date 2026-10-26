import pandas as pd

from src import availability as av
from src import config


def _elements(rows):
    """rows: (id, team, element_type, status, chance)."""
    return pd.DataFrame(rows, columns=["id", "team", "element_type", "status", "chance_of_playing_next_round"])


def _matches(players, events=(1, 2, 3, 4, 5, 6)):
    """players: (element, team_id, element_type, xg, xa, minutes) per match."""
    rows = []
    for ev in events:
        for el, team, et, xg, xa, mins in players:
            rows.append({"element": el, "team_id": team, "element_type": et, "event": ev,
                         "minutes": mins, "expected_goals": xg, "expected_assists": xa})
    return pd.DataFrame(rows)


# Team 1: striker 9 (0.30 of xG+xA), midfielder 8 (0.25), others 0.45; keeper 1 + 4 defenders.
TEAM1 = [(9, 1, 4, 0.5, 0.1, 90), (8, 1, 3, 0.3, 0.2, 90), (7, 1, 3, 0.4, 0.5, 90),
         (1, 1, 1, 0.0, 0.0, 90), (2, 1, 2, 0.0, 0.0, 90), (3, 1, 2, 0.0, 0.0, 90),
         (4, 1, 2, 0.0, 0.0, 90), (5, 1, 2, 0.0, 0.0, 90)]


def test_play_probability_by_status():
    p = av.play_probability(_elements([(1, 1, 3, "a", None), (2, 1, 3, "a", 75), (3, 1, 3, "d", None),
                                       (4, 1, 3, "i", 0), (5, 1, 3, "s", None)]))
    assert list(p.loc[[1, 2, 3, 4, 5]]) == [1.0, 0.75, config.AVAIL_DOUBT_DEFAULT_CHANCE, 0.0, 0.0]


def test_shares_use_only_matches_before_gw_start():
    m = _matches(TEAM1)
    haul = m[m.event == 6].copy()
    haul["event"] = 9
    haul.loc[haul.element == 8, "expected_goals"] = 5.0
    a = av.team_shares(m, 9).set_index("element")
    b = av.team_shares(pd.concat([m, haul]), 9).set_index("element")
    assert abs(a.loc[8, "attack_share"] - b.loc[8, "attack_share"]) < 1e-12
    assert abs(a.loc[9, "attack_share"] - 0.30) < 1e-9
    assert abs(a.loc[1, "defence_share"] - 0.2) < 1e-9 and a.loc[9, "defence_share"] == 0.0


def _striker(status, chance):
    els = _elements([(9, 1, 4, status, chance), (8, 1, 3, "a", None), (7, 1, 3, "a", None)])
    shares = av.team_shares(_matches(TEAM1), 9)
    return els, shares


def test_striker_out_cuts_attack_and_teammates():
    els, shares = _striker("s", None)
    missing = av.team_missing(shares, els, 5)
    assert abs(missing[1]["attack"] - 0.30) < 1e-9
    rated = av.apply_to_ratings({1: {"attack": 1.0, "defense": 1.0}, 2: {"attack": 1.0, "defense": 1.0}}, missing)
    assert abs(rated[1]["attack"] - (1 - config.AVAIL_ATTACK_IMPACT * 0.30)) < 1e-9
    assert rated[2] == {"attack": 1.0, "defense": 1.0}
    mult = av.teammate_multiplier(shares, els, missing, 5)
    assert abs(mult.loc[8] - (1 - config.AVAIL_TEAMMATE_IMPACT * 0.30)) < 1e-9


def test_doubt_covers_one_gw_of_the_horizon():
    els, shares = _striker("d", 50)
    missing = av.team_missing(shares, els, 5)
    assert abs(missing[1]["attack"] - 0.30 * 0.5 * 0.2) < 1e-9


def test_floor_holds_with_several_out():
    els = _elements([(9, 1, 4, "i", None), (8, 1, 3, "i", None), (7, 1, 3, "i", None), (2, 1, 2, "a", None)])
    shares = av.team_shares(_matches(TEAM1), 9)
    els = pd.concat([els, _elements([(6, 1, 3, "a", None)])])
    mult = av.teammate_multiplier(shares, els, av.team_missing(shares, els, 5), 5)
    assert abs(mult.loc[6] - config.AVAIL_TEAMMATE_FLOOR) < 1e-9


def test_no_history_team_unchanged():
    els = _elements([(50, 3, 4, "i", None), (51, 3, 3, "a", None)])
    shares = av.team_shares(_matches(TEAM1), 9)
    missing = av.team_missing(shares, els, 5)
    assert 3 not in missing
    assert av.apply_to_ratings({3: {"attack": 1.1, "defense": 0.9}}, missing)[3] == {"attack": 1.1, "defense": 0.9}
    assert av.teammate_multiplier(shares, els, missing, 5).loc[51] == 1.0


def test_out_player_ignores_own_share():
    els, shares = _striker("s", None)
    mult = av.teammate_multiplier(shares, els, av.team_missing(shares, els, 5), 5)
    assert mult.loc[9] == 1.0


def test_ratings_with_non_team_entries_pass_through():
    ratings = {1: {"attack": 1.0, "defense": 1.0}, "_league_avg_xg": 1.4}
    out = av.apply_to_ratings(ratings, {1: {"attack": 0.5, "defence": 0.0}})
    assert out["_league_avg_xg"] == 1.4
    assert out[1]["attack"] < 1.0
