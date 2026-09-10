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
    # HotGK at 7.5 still wins after the 3-pair penalty (7.5 - 2.25 > 4.8);
    # the surviving pairs are surfaced for the UI.
    build = optimizer.build_free_hit_squad(
        _market_h2h(hot_gk_score=7.5), "xpts_gw4", 100.0, opponents=_OPPONENTS
    )
    xi, _ = _xi_and_bench(build["squad_df"])
    assert int(xi[xi["pos"] == "GKP"].iloc[0]["id"]) == 1
    pairs = build["h2h_conflicts"]
    assert len(pairs) == 3
    assert all(p["defender"] == "HotGK" for p in pairs)
    assert {p["attacker"] for p in pairs} == {"OppMid1", "OppMid2", "OppFwd"}
    assert "H2H" in build["reason"] or "h2h" in build["reason"]
