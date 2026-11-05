"""Best eleven, line-up from a squad, and eleven scoring, on real GW9 2026-27 data."""
import itertools
import json
import pathlib

import pandas as pd

from src import monitor_xi
from src.optimizer import VALID_FORMATIONS

FIX = pathlib.Path("tests/fixtures/monitor")


def gw9():
    return pd.read_csv(FIX / "gw9_snapshots.csv")


def expected():
    return json.loads((FIX / "gw9_expected.json").read_text())


def points_minutes(df):
    return (dict(zip(df.player_id.astype(int), df.actual_points.astype(int))),
            dict(zip(df.player_id.astype(int), df.actual_minutes.astype(int))))


def small_pool():
    """16 players, four clubs. Club A holds the six highest values, so taking the
    top values and then repairing the 3-per-club cap is not optimal. (Four clubs:
    three could field at most nine players under a cap of three.)"""
    rows = [
        (1, "GKP", "A", 9.0), (2, "GKP", "B", 4.0),
        (3, "DEF", "A", 8.0), (4, "DEF", "A", 7.9), (5, "DEF", "B", 5.0), (6, "DEF", "C", 4.9), (7, "DEF", "D", 4.0),
        (8, "MID", "A", 8.5), (9, "MID", "A", 8.4), (10, "MID", "B", 6.0), (11, "MID", "C", 5.5), (12, "MID", "D", 3.0),
        (13, "FWD", "A", 9.5), (14, "FWD", "B", 6.5), (15, "FWD", "C", 6.4), (16, "FWD", "D", 2.0),
    ]
    return pd.DataFrame(rows, columns=["player_id", "pos", "team_short", "value"])


def is_legal(xi, max_per_club):
    counts = xi.pos.value_counts().to_dict()
    shape = (counts.get("DEF", 0), counts.get("MID", 0), counts.get("FWD", 0))
    return (len(xi) == 11 and counts.get("GKP", 0) == 1 and shape in VALID_FORMATIONS
            and (max_per_club is None or xi.team_short.value_counts().max() <= max_per_club))


def brute_force_best(pool, max_per_club):
    best = None
    for combo in itertools.combinations(pool.player_id, 11):
        xi = pool[pool.player_id.isin(combo)]
        if is_legal(xi, max_per_club):
            total = xi.value.sum()
            best = total if best is None or total > best else best
    return best


def total(pool, ids):
    return pool[pool.player_id.isin(ids)].value.sum()


def test_best_xi_is_exact_against_brute_force_with_a_club_cap():
    pool = small_pool()
    ids = monitor_xi.best_xi(pool, 3)
    assert is_legal(pool[pool.player_id.isin(ids)], 3)
    assert abs(total(pool, ids) - brute_force_best(pool, 3)) < 1e-9


def test_best_xi_without_a_cap_matches_brute_force_too():
    pool = small_pool()
    ids = monitor_xi.best_xi(pool, None)
    assert abs(total(pool, ids) - brute_force_best(pool, None)) < 1e-9
    assert total(pool, ids) > total(pool, monitor_xi.best_xi(pool, 3))   # the cap costs something here


def test_best_xi_is_deterministic_on_ties():
    pool = small_pool()
    pool.loc[pool.player_id.isin([14, 15]), "value"] = 6.5
    assert monitor_xi.best_xi(pool, 3) == monitor_xi.best_xi(pool.sample(frac=1, random_state=3), 3)


def test_best_xi_returns_nothing_when_no_legal_eleven_exists():
    pool = small_pool()
    assert monitor_xi.best_xi(pool[pool.pos != "GKP"], 3) == []


def test_best_xi_is_legal_on_real_gw9_and_at_least_as_good_as_the_hand_built_one():
    pool = gw9().rename(columns={"model_xpts": "value"})
    xi = pool[pool.player_id.isin(monitor_xi.best_xi(pool, 3))]
    assert is_legal(xi, 3)
    assert xi.value.sum() >= expected()["hand_built_app_xi_projected"] - 0.05


def test_best_possible_gw9_is_115():
    pool = gw9().rename(columns={"actual_points": "value"})
    ids = monitor_xi.best_xi(pool, 3)
    assert int(total(pool, ids)) == expected()["best_possible"]


def test_scout_gw9_scores_69_without_captain_and_71_with_haaland():
    e = expected()
    pts, mins = points_minutes(gw9())
    assert monitor_xi.score_xi(e["scout_ids"], None, None, pts, mins) == {
        "no_captain": 69, "with_captain": None, "captain_used": None, "missing": []}
    assert monitor_xi.score_xi(e["scout_ids"], 411, None, pts, mins)["with_captain"] == 71


def test_owner_gw9_eleven_scores_64():
    e = expected()
    pts, mins = points_minutes(gw9())
    out = monitor_xi.score_xi(e["owner_picks"][:11], e["owner_captain"], e["owner_vice"], pts, mins)
    assert out["with_captain"] == e["owner_points"] and out["captain_used"] == 411


def test_vice_is_doubled_when_captain_did_not_play():
    assert monitor_xi.score_xi([1, 2], 1, 2, {1: 0, 2: 5}, {1: 0, 2: 90}) == {
        "no_captain": 5, "with_captain": 10, "captain_used": 2, "missing": []}


def test_nobody_is_doubled_when_neither_captain_nor_vice_played():
    out = monitor_xi.score_xi([1, 2, 3], 1, 2, {1: 0, 2: 0, 3: 6}, {1: 0, 2: 0, 3: 90})
    assert (out["with_captain"], out["captain_used"]) == (6, None)


def test_a_player_without_points_is_reported_not_silently_zero():
    out = monitor_xi.score_xi([1, 9], None, None, {1: 4}, {1: 90})
    assert out["no_captain"] == 4 and out["missing"] == [9]


def test_app_captain_uses_the_product_rule_not_the_highest_projection():
    # A defender with the highest projection loses the armband to a forward: the
    # product's rule weights position ceilings (captain_advisor), and the dashboard
    # must test the rule the app really uses.
    xi = pd.DataFrame({
        "player_id": [1, 2, 3], "web_name": ["Def", "Fwd", "Mid"], "pos": ["DEF", "FWD", "MID"],
        "team_short": ["A", "B", "C"], "price_m": [5.0, 7.0, 6.0], "xpts": [6.0, 5.9, 4.0],
    })
    from src import captain_advisor
    want = [r.player_id for r in captain_advisor.recommend_captain(
        xi.rename(columns={"web_name": "name", "team_short": "team"}), top_n=2)]
    assert monitor_xi.app_captain(xi) == (want[0], want[1])
    assert monitor_xi.app_captain(xi)[0] == 2


def test_pick_lineup_fields_a_legal_eleven_from_the_owner_fifteen():
    e = expected()
    df = gw9()
    squad = df[df.player_id.isin(e["owner_picks"])].rename(columns={"model_xpts": "xpts"})
    out = monitor_xi.pick_lineup(squad)
    xi = squad[squad.player_id.isin(out["xi"])]
    assert is_legal(xi, None) and sorted(out["xi"] + out["bench"]) == sorted(e["owner_picks"])
    assert out["captain_id"] == 411 and out["vice_id"] in out["xi"] and out["vice_id"] != 411


def test_pick_lineup_with_fewer_than_eleven_fields_who_it_has():
    squad = gw9().rename(columns={"model_xpts": "xpts"}).head(5)
    out = monitor_xi.pick_lineup(squad)
    assert sorted(out["xi"]) == sorted(squad.player_id.tolist()) and out["bench"] == []
