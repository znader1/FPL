import math

from src.stack_odds import stack_odds_for_xi


def _xi(rows):
    return [
        {"player_id": pid, "web_name": name, "pos": pos, "team": team}
        for pid, name, pos, team in rows
    ]


BASE_XI = _xi([
    (1, "GK", "GKP", 10),
    (2, "D1", "DEF", 11), (3, "D2", "DEF", 12), (4, "D3", "DEF", 13),
    (5, "M1", "MID", 1), (6, "M2", "MID", 1), (7, "M3", "MID", 14),
    (8, "M4", "MID", 15), (9, "F1", "FWD", 1),
    (10, "F2", "FWD", 16), (11, "F3", "FWD", 17),
])  # three attackers from team 1


def test_no_stack_returns_empty():
    xi = _xi([(i, f"P{i}", "MID", i) for i in range(1, 12)])  # all distinct teams
    assert stack_odds_for_xi(xi, {i: 1.5 for i in range(1, 12)}, {}) == []


def test_stack_detected_with_probabilities_in_range():
    out = stack_odds_for_xi(BASE_XI, {1: 2.0}, {})
    assert len(out) == 1
    row = out[0]
    assert row["team"] == 1 and row["n"] == 3
    assert set(row["players"]) == {"M1", "M2", "F1"}
    assert 0.0 < row["p_all_return"] < 1.0
    assert 0.0 < row["p_all_blank"] < 1.0
    assert row["p_all_return"] + row["p_all_blank"] <= 1.0


def test_tight_defence_crushes_all_return_and_raises_all_blank():
    tight = stack_odds_for_xi(BASE_XI, {1: 1.3}, {})[0]
    leaky = stack_odds_for_xi(BASE_XI, {1: 2.4}, {})[0]
    assert leaky["p_all_return"] > tight["p_all_return"]
    assert tight["p_all_blank"] > leaky["p_all_blank"]


def test_all_blank_at_least_probability_of_zero_goals():
    lam = 1.3
    row = stack_odds_for_xi(BASE_XI, {1: lam}, {})[0]
    assert row["p_all_blank"] >= math.exp(-lam) - 1e-9


def test_missing_lambda_skips_stack():
    assert stack_odds_for_xi(BASE_XI, {}, {}) == []


def test_defensive_players_do_not_count_toward_stack():
    xi = _xi([
        (1, "GK", "GKP", 1), (2, "D1", "DEF", 1),  # same team but defensive
        (3, "M1", "MID", 1),
        (4, "D2", "DEF", 12), (5, "D3", "DEF", 13), (6, "D4", "DEF", 14),
        (7, "M2", "MID", 15), (8, "M3", "MID", 16), (9, "M4", "MID", 17),
        (10, "F1", "FWD", 18), (11, "F2", "FWD", 19),
    ])
    assert stack_odds_for_xi(xi, {1: 2.0}, {}) == []  # only one attacker from team 1


def test_shares_from_xgi_shift_probability():
    # Concentrated involvement (one player owns most xGI) makes "all three
    # return" harder than a balanced trio.
    balanced = stack_odds_for_xi(BASE_XI, {1: 2.0}, {5: 0.5, 6: 0.5, 9: 0.5})[0]
    skewed = stack_odds_for_xi(BASE_XI, {1: 2.0}, {5: 1.2, 6: 0.15, 9: 0.15})[0]
    assert balanced["p_all_return"] > skewed["p_all_return"]
