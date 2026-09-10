import pandas as pd

from src import optimizer


def _market():
    """League-wide market: one elite GK, one mid GK, two 4.0m backups, and
    enough outfielders (teams spread so the 3-per-team cap never binds)."""
    rows = [
        # id, name, pos, team, price, xpts
        (1, "GoodGK", "GKP", 1, 5.5, 5.0),
        (2, "MidGK", "GKP", 2, 4.5, 4.0),
        (3, "BackupA", "GKP", 3, 4.0, 0.5),
        (4, "BackupB", "GKP", 4, 4.0, 0.9),
    ]
    pid = 10
    for i in range(8):
        rows.append((pid, f"D{i}", "DEF", 5 + i, 5.0, 4.5 - i * 0.1))
        pid += 1
    for i in range(8):
        rows.append((pid, f"M{i}", "MID", 5 + i, 6.0, 5.5 - i * 0.1))
        pid += 1
    for i in range(5):
        rows.append((pid, f"F{i}", "FWD", 13 + i, 6.5, 5.8 - i * 0.1))
        pid += 1
    return pd.DataFrame(rows, columns=["id", "web_name", "pos", "team", "price_m", "xpts_gw4"])


def _xi_and_bench(squad_df):
    # build_free_hit_squad returns best_xi rows first, then the 4 bench rows.
    return squad_df.iloc[:11], squad_df.iloc[11:]


def test_free_hit_xi_gk_picked_by_score_not_price():
    build = optimizer.build_free_hit_squad(
        elements_all=_market(), score_col="xpts_gw4", budget_m=100.0
    )
    assert build["ok"], build["reason"]
    xi, bench = _xi_and_bench(build["squad_df"])

    xi_gk = xi[xi["pos"] == "GKP"]
    assert len(xi_gk) == 1
    # Best-scoring affordable keeper starts — not the 2nd-cheapest backup.
    assert int(xi_gk.iloc[0]["id"]) == 1
    assert float(xi_gk.iloc[0]["chip_score"]) == 5.0

    bench_gk = bench[bench["pos"] == "GKP"]
    assert len(bench_gk) == 1
    assert float(bench_gk.iloc[0]["price_m"]) == 4.0  # bench keeper stays fodder


def test_free_hit_gk_pick_deterministic():
    a = optimizer.build_free_hit_squad(_market(), "xpts_gw4", 100.0)
    b = optimizer.build_free_hit_squad(_market(), "xpts_gw4", 100.0)
    assert a["squad_df"]["id"].tolist() == b["squad_df"]["id"].tolist()


def test_free_hit_squad_still_legal():
    build = optimizer.build_free_hit_squad(_market(), "xpts_gw4", 100.0)
    squad = build["squad_df"]
    assert len(squad) == 15
    assert (squad["pos"] == "GKP").sum() == 2
    assert float(squad["price_m"].sum()) <= 100.0
    assert squad["team"].value_counts().max() <= 3


def test_injured_players_excluded_from_chip_market():
    m = _market()
    m["status"] = "a"
    m.loc[m["id"] == 1, "status"] = "i"  # GoodGK injured
    build = optimizer.build_free_hit_squad(m, "xpts_gw4", 100.0)
    assert build["ok"], build["reason"]
    assert 1 not in build["squad_df"]["id"].tolist()


def test_bench_prefers_players_with_minutes():
    m = _market()
    m["status"] = "a"
    m["minutes"] = 270
    # Two extra 4.0m keepers: a zero-minutes body and a playing backup.
    extra = pd.DataFrame(
        [
            (50, "NoMinGK", "GKP", 23, 4.0, 0.4),
            (51, "PlayingGK", "GKP", 24, 4.0, 0.4),
        ],
        columns=["id", "web_name", "pos", "team", "price_m", "xpts_gw4"],
    )
    extra["status"] = "a"
    extra["minutes"] = [0, 270]
    m = pd.concat([m, extra], ignore_index=True)
    build = optimizer.build_free_hit_squad(m, "xpts_gw4", 100.0)
    _, bench = _xi_and_bench(build["squad_df"])
    bench_gk_id = int(bench[bench["pos"] == "GKP"].iloc[0]["id"])
    assert bench_gk_id != 50  # zero-minutes body skipped for the playing one


def test_bench_minutes_floor_relaxes_when_market_is_thin():
    m = _market()
    m["status"] = "a"
    m["minutes"] = 0  # nobody meets the floor — build must still succeed
    build = optimizer.build_free_hit_squad(m, "xpts_gw4", 100.0)
    assert build["ok"], build["reason"]
    assert len(build["squad_df"]) == 15


def _market_h2h(hot_gk_score=5.0):
    """Team 1's keeper faces team 2, whose three attackers top the market.
    A near-as-good keeper on team 20 has no conflicting picks."""
    rows = [
        (1, "HotGK", "GKP", 1, 5.5, hot_gk_score),
        (2, "CleanGK", "GKP", 20, 5.0, 4.8),
        (3, "BackupA", "GKP", 21, 4.0, 0.5),
        (4, "BackupB", "GKP", 22, 4.0, 0.6),
        (30, "OppMid1", "MID", 2, 6.0, 5.9),
        (31, "OppMid2", "MID", 2, 6.0, 5.8),
        (40, "OppFwd", "FWD", 2, 6.5, 6.0),
    ]
    pid = 10
    for i in range(8):
        rows.append((pid, f"D{i}", "DEF", 5 + i, 5.0, 4.5 - i * 0.1))
        pid += 1
    for i in range(6):
        rows.append((pid, f"M{i}", "MID", 5 + i, 6.0, 5.5 - i * 0.1))
        pid += 1
    for i in range(4):
        rows.append((pid, f"F{i}", "FWD", 13 + i, 6.5, 5.6 - i * 0.1))
        pid += 1
    return pd.DataFrame(rows, columns=["id", "web_name", "pos", "team", "price_m", "xpts_gw4"])


_OPPONENTS = {1: {2}, 2: {1}}


def test_h2h_penalty_moves_keeper_off_conflicted_pick():
    # Team 2's three attackers make the XI; HotGK (5.0) faces all of them, so
    # 3 × 0.75 penalty drops him below CleanGK (4.8).
    build = optimizer.build_free_hit_squad(
        _market_h2h(), "xpts_gw4", 100.0, opponents=_OPPONENTS
    )
    assert build["ok"], build["reason"]
    xi, _ = _xi_and_bench(build["squad_df"])
    assert int(xi[xi["pos"] == "GKP"].iloc[0]["id"]) == 2
    assert build["h2h_conflicts"] == []


def test_h2h_no_opponents_map_keeps_raw_pick():
    build = optimizer.build_free_hit_squad(_market_h2h(), "xpts_gw4", 100.0)
    xi, _ = _xi_and_bench(build["squad_df"])
    assert int(xi[xi["pos"] == "GKP"].iloc[0]["id"]) == 1
    assert build["h2h_conflicts"] == []


def test_h2h_conflict_survives_when_clearly_better_and_is_reported():
    # The attacker-stack limit keeps team 2's third attacker (OppFwd) out, so
    # two conflicting pairs remain; HotGK at 7.5 still wins after the 2-pair
    # penalty (7.5 - 1.5 > 4.8) and the surviving pairs are surfaced.
    build = optimizer.build_free_hit_squad(
        _market_h2h(hot_gk_score=7.5), "xpts_gw4", 100.0, opponents=_OPPONENTS
    )
    xi, _ = _xi_and_bench(build["squad_df"])
    assert int(xi[xi["pos"] == "GKP"].iloc[0]["id"]) == 1
    pairs = build["h2h_conflicts"]
    assert len(pairs) == 2
    assert all(p["defender"] == "HotGK" for p in pairs)
    assert {p["attacker"] for p in pairs} == {"OppMid1", "OppMid2"}
    assert "H2H" in build["reason"] or "h2h" in build["reason"]


# ---- ceiling-aware captain (fixture difficulty term) ----

def test_captain_prefers_easier_fixture_on_near_tie():
    squad = pd.DataFrame({
        "player_id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
        "pos": ["GKP", "GKP"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3,
        "team": list(range(1, 16)),
        "web_name": [f"P{i}" for i in range(1, 16)],
    })
    proj = pd.DataFrame({
        "id": range(1, 16),
        "xpts_gw4": [4.0, 1.0, 4.5, 4.4, 4.3, 4.2, 4.1,
                     6.7, 6.6, 4.9, 4.8, 4.7,
                     5.0, 4.6, 4.5],
        "diff_avg_gw4": [3, 3, 3, 3, 3, 3, 3,
                         4, 2, 3, 3, 3,   # id8 MID 6.7 on D4; id9 MID 6.6 on D2
                         3, 3, 3],
        "price_m": [5.0] * 15,
    })
    res = optimizer.optimize_lineup(squad, proj, "xpts_gw4")
    # Same position, near-tie on mean (6.7 vs 6.6): position multiplier is
    # identical, so only the fixture-difficulty term can flip the armband to
    # the D2 fixture. Without it, raw mean picks id8.
    assert res["captain_player_id"] == 9


# ---- differential mode (ownership penalty) ----

def test_differential_mode_prefers_low_owned_near_equal():
    m = _market()
    m["selected_by_percent"] = 5.0
    # Two near-equal MIDs: template (55% owned) barely ahead of a 4%-owned one.
    m.loc[m["id"] == 18, "selected_by_percent"] = 55.0   # M0: xpts 5.5
    m.loc[m["id"] == 19, "selected_by_percent"] = 4.0    # M1: xpts 5.4
    base = optimizer.build_free_hit_squad(m, "xpts_gw4", 100.0)
    diff = optimizer.build_free_hit_squad(m, "xpts_gw4", 100.0, differential=True)
    base_xi, _ = _xi_and_bench(base["squad_df"])
    diff_xi, _ = _xi_and_bench(diff["squad_df"])
    assert 18 in base_xi["id"].tolist()
    # Differential: 5.5 × (1 − .35×.55) ≈ 4.44 < 5.4 × (1 − .35×.04) ≈ 5.32
    diff_ids = diff_xi["id"].tolist()
    assert 19 in diff_ids


# ---- soft attacker-stack limit ----

def test_third_same_team_attacker_penalized():
    m = _market()
    # Three team-30 attackers top the market; a spread alternative sits just under.
    stack = pd.DataFrame(
        [
            (60, "S1", "MID", 30, 6.0, 6.5),
            (61, "S2", "MID", 30, 6.0, 6.4),
            (62, "S3", "FWD", 30, 6.5, 6.1),
            (63, "Alt", "FWD", 31, 6.5, 6.0),
        ],
        columns=["id", "web_name", "pos", "team", "price_m", "xpts_gw4"],
    )
    m = pd.concat([m, stack], ignore_index=True)
    build = optimizer.build_free_hit_squad(m, "xpts_gw4", 100.0)
    xi, _ = _xi_and_bench(build["squad_df"])
    ids = set(xi["id"].tolist())
    # First two stackers stay (no penalty); the third (6.1 − 0.6 = 5.5) drops
    # below the spread alternative (6.0) and the base FWDs (5.8/5.7).
    assert {60, 61}.issubset(ids)
    assert 63 in ids and 62 not in ids


# ---- bench team diversity ----

def test_bench_prefers_distinct_teams():
    m = _market()
    m["minutes"] = 270
    m["status"] = "a"
    # Cheap 4.0 bench tier per position: a duplicated team first in sort
    # order, plus a distinct-team alternative at the same price.
    cheap = pd.DataFrame(
        [
            (70, "BD1", "DEF", 40, 4.0, 1.0),
            (71, "BD2", "DEF", 40, 4.0, 1.1),
            (72, "BD3", "DEF", 41, 4.0, 1.2),
            (73, "BM1", "MID", 40, 4.0, 1.0),
            (74, "BM2", "MID", 50, 4.0, 1.1),
            (75, "BF1", "FWD", 40, 4.0, 1.0),
            (76, "BF2", "FWD", 60, 4.0, 1.1),
        ],
        columns=["id", "web_name", "pos", "team", "price_m", "xpts_gw4"],
    )
    cheap["minutes"] = 270
    cheap["status"] = "a"
    m = pd.concat([m, cheap], ignore_index=True)
    build = optimizer.build_free_hit_squad(m, "xpts_gw4", 100.0)
    _, bench = _xi_and_bench(build["squad_df"])
    outfield_bench_teams = bench[bench["pos"] != "GKP"]["team"].tolist()
    # Whatever bench split the formation demands, equal-price distinct-team
    # alternatives exist for every position — no duplicated team allowed.
    assert len(set(outfield_bench_teams)) == len(outfield_bench_teams)
