import pandas as pd
import pytest

from src import chip_bench, config


def _market(mid_dc=True):
    """Market with a 3-4-3 XI already chosen (ids < 100) and bench candidates."""
    rows = []
    # bench GK candidates
    rows += [
        (201, "GKcheapGhost", "GKP", 1, 4.0, 0.5, 0.10, 0.1, 0.3, "a"),
        (202, "GKcheapPlays", "GKP", 2, 4.0, 1.5, 0.95, 0.1, 0.3, "a"),
        (203, "GKmid", "GKP", 3, 4.5, 2.5, 1.00, 0.1, 0.3, "a"),
    ]
    # DEF candidates
    rows += [
        (211, "DEFghost", "DEF", 4, 4.0, 0.4, 0.20, 0.1, 0.2, "a"),
        (212, "DEFplaysLowCS", "DEF", 5, 4.0, 2.0, 0.90, 0.6, 0.1, "a"),  # p_dc high
        (213, "DEFplaysCS", "DEF", 6, 4.2, 2.4, 0.95, 0.2, 0.45, "a"),
        (214, "DEFinjured", "DEF", 7, 4.0, 2.4, 0.95, 0.5, 0.5, "i"),
        (215, "DEFgood", "DEF", 8, 5.0, 3.5, 1.00, 0.5, 0.5, "a"),
    ]
    # MID candidates
    rows += [
        (221, "MIDcheapNoDC", "MID", 9, 4.5, 1.8, 0.90, 0.2 if mid_dc else 0.1, 0.0, "a"),
        (222, "MIDdc", "MID", 10, 5.0, 2.2, 0.90, 0.6 if mid_dc else 0.1, 0.0, "a"),
        (223, "MIDstar", "MID", 11, 7.0, 4.5, 1.00, 0.3, 0.0, "a"),
    ]
    # FWD candidate
    rows += [
        (231, "FWDcheap", "FWD", 12, 4.5, 1.9, 0.90, 0.0, 0.0, "a"),
        (232, "FWDghost", "FWD", 13, 4.5, 0.3, 0.10, 0.0, 0.0, "a"),
    ]
    df = pd.DataFrame(
        rows,
        columns=["id", "web_name", "pos", "team", "price_m", "chip_score", "start_share", "p_dc", "p_clean_sheet", "status"],
    )
    df["injury_flag"] = False
    return df


def _xi():
    # 1 GK, 3 DEF, 4 MID, 3 FWD on teams 14..24 so caps never bind.
    rows = [(1, "GK1", "GKP", 14)]
    rows += [(10 + i, f"D{i}", "DEF", 15 + i) for i in range(3)]
    rows += [(20 + i, f"M{i}", "MID", 18 + i) for i in range(4)]
    rows += [(30 + i, f"F{i}", "FWD", 22 + i) for i in range(3)]
    return pd.DataFrame(rows, columns=["id", "web_name", "pos", "team"])


def test_availability_requires_start_share_column():
    with pytest.raises(KeyError, match="start_share"):
        chip_bench.availability_mask(_market().drop(columns=["start_share"]), 0.85)


def test_availability_mask_filters_ghosts_and_injured():
    m = _market()
    mask = chip_bench.availability_mask(m, 0.85)
    ids = set(m.loc[mask, "id"])
    assert 201 not in ids and 214 not in ids and 211 not in ids
    assert 202 in ids and 215 in ids


def test_roles_bench_has_four_distinct_roles_and_plays():
    bench, notes = chip_bench.fill_bench(
        _market(), _xi(), mode="roles", budget_left_m=20.0, max_per_team=3, team_counts={}
    )
    assert len(bench) == 4
    assert set(bench["role"]) == {"gk2", "def_cover", "dc_mid", "free"}
    assert (bench["start_share"] >= config.CHIP_BENCH_START_SHARE).all()
    assert int(bench.loc[bench["role"] == "gk2", "id"].iloc[0]) == 202  # cheapest playing GK
    assert int(bench.loc[bench["role"] == "dc_mid", "id"].iloc[0]) == 222
    # 2/5/5/3 completed: XI has 3 DEF, 4 MID, 3 FWD → bench needs 2 DEF + 1 MID + 0 FWD + GK
    assert sorted(bench["pos"].tolist()) == ["DEF", "DEF", "GKP", "MID"]


def test_dc_mid_falls_back_to_def_with_note():
    bench, notes = chip_bench.fill_bench(
        _market(mid_dc=False), _xi(), mode="roles", budget_left_m=20.0, max_per_team=3, team_counts={}
    )
    row = bench[bench["role"] == "dc_mid"].iloc[0]
    assert row["pos"] == "DEF" and row["p_dc"] >= 0.5
    assert any("dc_mid fallback" in n for n in notes)
    # shape still completes: free slot took the missing MID
    assert sorted(bench["pos"].tolist()) == ["DEF", "DEF", "GKP", "MID"]


def test_bench_cost_within_budget_cap():
    bench, _ = chip_bench.fill_bench(
        _market(), _xi(), mode="roles", budget_left_m=17.5, max_per_team=3, team_counts={}
    )
    assert float(bench["price_m"].sum()) <= 17.5 + 1e-9


def test_enablers_mode_is_cheapest_playing():
    bench, _ = chip_bench.fill_bench(
        _market(), _xi(), mode="enablers", budget_left_m=20.0, max_per_team=3, team_counts={}
    )
    assert set(bench["role"]) == {"enabler"}
    assert sorted(bench["id"].tolist()) == [202, 212, 213, 221]


def _xi_532():
    rows = [(1, "GK1", "GKP", 14)]
    rows += [(10 + i, f"D{i}", "DEF", 15 + i) for i in range(5)]
    rows += [(20 + i, f"M{i}", "MID", 20 + i) for i in range(3)]
    rows += [(30 + i, f"F{i}", "FWD", 23 + i) for i in range(2)]
    return pd.DataFrame(rows, columns=["id", "web_name", "pos", "team"])


def test_dc_mid_takes_best_available_p_dc_before_cheapest():
    # No DEF slot left on the bench and no MID reaches the 0.5 floor: the role
    # must go to the MID with the best DC odds (0.3), not the cheapest body.
    bench, notes = chip_bench.fill_bench(
        _market(mid_dc=False), _xi_532(), mode="roles", budget_left_m=20.0, max_per_team=3, team_counts={}
    )
    row = bench[bench["role"] == "dc_mid"].iloc[0]
    assert int(row["id"]) == 223
    assert any("best available" in n for n in notes)
    assert not any("cheapest" in n for n in notes)


def test_gk2_prefers_home_away_rotation_with_the_starting_keeper():
    # Two cheap playing keepers at the same price: 202 mirrors the XI keeper's
    # fixtures (no rotation value), 203 is home exactly when the XI keeper is
    # away. The bench slot must take 203 even though 202 scores the same.
    m = _market()
    gws = ["fixtures_gw8", "fixtures_gw9", "fixtures_gw10", "fixtures_gw11", "fixtures_gw12"]
    for c in gws:
        m[c] = "H-AAA(D3)"
    xi = _xi()
    xi_gk = pd.DataFrame([{"id": 1, "web_name": "GK1", "pos": "GKP", "team": 14}])
    m = pd.concat([m, xi_gk.assign(price_m=5.0, chip_score=4.0, start_share=1.0, p_dc=0.0, p_clean_sheet=0.3, status="a", injury_flag=False)], ignore_index=True)
    m.loc[m["id"] == 1, gws] = ["H-X(D3)", "A-X(D3)", "H-X(D3)", "A-X(D3)", "H-X(D3)"]
    m.loc[m["id"] == 202, gws] = ["H-X(D3)", "A-X(D3)", "H-X(D3)", "A-X(D3)", "H-X(D3)"]
    m.loc[m["id"] == 203, gws] = ["A-X(D3)", "H-X(D3)", "A-X(D3)", "H-X(D3)", "A-X(D3)"]
    m.loc[m["id"] == 203, "price_m"] = 4.0
    m.loc[m["id"] == 203, "chip_score"] = 1.5
    bench, _ = chip_bench.fill_bench(m, xi, mode="roles", budget_left_m=20.0, max_per_team=3, team_counts={})
    assert int(bench.loc[bench["role"] == "gk2", "id"].iloc[0]) == 203
