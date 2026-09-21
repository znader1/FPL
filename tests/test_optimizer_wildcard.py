"""XI-first wildcard builder (optimizer.build_wildcard_squad)."""
import pandas as pd
import pytest

from src import config, optimizer

GWS = [6, 7, 8]
GW_COLS = [f"xpts_gw{g}" for g in GWS]


def _row(pid, name, pos, team, price, per_gw, starts=1.0, minutes=400, status="a"):
    r = {"id": pid, "web_name": name, "pos": pos, "team": team, "price_m": price,
         "status": status, "minutes": minutes, "selected_by_percent": 10.0,
         "recent_gw_avg_starts": starts, "recent_gw_samples": 4}
    for g, v in zip(GWS, per_gw):
        r[f"xpts_gw{g}"] = v
    r["xpts_horizon"] = float(sum(per_gw))
    return r


def _market(defender_uplift=0.0, gated_star=False):
    """20 teams; every position has cheap bodies and a few stars. Team ids are
    spread so the 3-per-team cap never binds unless a test wants it to."""
    rows, pid = [], 1
    # Keepers: one starter-quality per team (cheap), two "rotation" keepers whose
    # home weeks alternate, and 4.0m fodder.
    for t in range(1, 21):
        rows.append(_row(pid, f"GK{t}", "GKP", t, 4.5 + (0.5 if t <= 2 else 0.0), [3.5, 3.5, 3.5])); pid += 1
    rows.append(_row(pid, "RotGK_A", "GKP", 3, 4.4, [4.6, 2.0, 4.6])); pid += 1
    rows.append(_row(pid, "RotGK_B", "GKP", 4, 4.4, [2.0, 4.6, 2.0])); pid += 1
    rows.append(_row(pid, "FodderGK", "GKP", 5, 4.0, [1.0, 1.0, 1.0], minutes=0)); pid += 1
    # Defenders: 7 per team-ish, cheap-ish, decent.
    for i in range(30):
        base = 3.2 + defender_uplift + (0.02 * i)
        rows.append(_row(pid, f"DEF{i}", "DEF", 1 + (i % 20), 4.0 + 0.1 * (i % 6), [base] * 3)); pid += 1
    # Home weeks in GW6/8, away blank in GW7: horizon 10.4 keeps him OUT of the
    # XI (the flat starters sum ~11.1) but he out-projects the weakest starter
    # twice → the rotation defender.
    rows.append(_row(pid, "RotDEF_home", "DEF", 6, 4.3, [4.6, 1.2, 4.6])); pid += 1
    rows.append(_row(pid, "FodderDEF", "DEF", 7, 4.0, [0.8, 0.8, 0.8], minutes=0)); pid += 1
    # Midfielders: premiums + mids + cheap.
    for i in range(30):
        price = 12.5 if i < 3 else (7.5 if i < 10 else 5.0)
        base = 7.0 if i < 3 else (5.0 if i < 10 else 3.0)
        rows.append(_row(pid, f"MID{i}", "MID", 1 + (i % 20), price, [base] * 3)); pid += 1
    # A rotation-risk star: highest score but starts 30% of games.
    rows.append(_row(pid, "RotRiskStar", "MID", 8, 8.0, [9.0, 9.0, 9.0], starts=0.3 if gated_star else 1.0)); pid += 1
    # Forwards.
    for i in range(15):
        price = 14.0 if i < 2 else (7.0 if i < 6 else 4.5)
        base = 7.5 if i < 2 else (4.8 if i < 6 else 2.8)
        rows.append(_row(pid, f"FWD{i}", "FWD", 1 + (i % 20), price, [base] * 3)); pid += 1
    return pd.DataFrame(rows)


def _build(m, budget=100.0, **kw):
    return optimizer.build_wildcard_squad(m, "xpts_horizon", budget, gw_cols=GW_COLS, **kw)


def test_builds_legal_15_within_budget_xi_first():
    build = _build(_market())
    assert build["ok"], build["reason"]
    sq = build["squad_df"]
    assert len(sq) == 15
    assert (sq["pos"] == "GKP").sum() == 2
    assert (sq["pos"] == "DEF").sum() == 5
    assert (sq["pos"] == "MID").sum() == 5
    assert (sq["pos"] == "FWD").sum() == 3
    assert float(sq["price_m"].sum()) <= 100.0 + 1e-9
    assert sq["team"].value_counts().max() <= 3
    d, m, f = build["formation"]
    assert (d, m, f) in optimizer.VALID_FORMATIONS
    # XI rows first: their shape is the formation.
    xi = sq.head(11)
    assert (xi["pos"] == "GKP").sum() == 1
    assert (xi["pos"] == "DEF").sum() == d
    assert (xi["pos"] == "MID").sum() == m
    assert (xi["pos"] == "FWD").sum() == f
    assert build["xi_player_ids"] == xi["player_id"].tolist()


def test_bench_is_cheap_and_budget_goes_to_the_xi():
    build = _build(_market())
    sq = build["squad_df"]
    bench = sq.tail(4)
    gk_cap = float(getattr(config, "CHIP_WILDCARD_BENCH_GK_MAX_PRICE", 4.5))
    assert float(bench[bench["pos"] == "GKP"]["price_m"].iloc[0]) <= gk_cap
    # Bench never carries a premium; the XI does.
    assert float(bench["price_m"].max()) < 6.0
    assert float(sq.head(11)["price_m"].max()) >= 12.0


def test_rotation_keeper_chosen_over_fodder_when_he_complements_the_xi_keeper():
    """XI keeper is a flat 3.5/GW body; RotGK_A projects 4.6 at home in GW6/8 —
    he adds (4.6-3.5)*2 = 2.2 by rotation, so he is the bench keeper, not the
    4.0m ghost."""
    m = _market()
    # Make one keeper clearly the XI pick so the complement target is fixed.
    m.loc[m["web_name"] == "GK1", GW_COLS] = 3.5
    build = _build(m)
    rot = build["bench_rotation"]["GKP"]
    assert rot["web_name"] in ("RotGK_A", "RotGK_B")
    assert rot["rotation_xpts"] > 0
    assert "by rotation" in build["reason"]


def test_rotation_defender_complements_weakest_xi_defender():
    build = _build(_market())
    assert "DEF" in build["bench_rotation"]
    rot = build["bench_rotation"]["DEF"]
    assert rot["web_name"] == "RotDEF_home"
    assert rot["rotation_xpts"] > 0
    def_cap = float(getattr(config, "CHIP_WILDCARD_BENCH_ROTATION_DEF_MAX_PRICE", 4.5))
    assert rot["price_m"] <= def_cap


def test_no_gw_columns_falls_back_to_cheapest_playing_bench():
    m = _market()
    build = optimizer.build_wildcard_squad(m, "xpts_horizon", 100.0, gw_cols=None)
    assert build["ok"], build["reason"]
    bench = build["squad_df"].tail(4)
    # Fodder with 0 minutes is still avoided when a playing body costs the same.
    assert "FodderGK" not in bench["web_name"].tolist()
    assert build["bench_rotation"]["GKP"]["rotation_xpts"] == 0.0


def test_rotation_risk_star_kept_off_the_xi_but_allowed_on_bench():
    m = _market(gated_star=True)
    build = _build(m)
    assert build["xi_gated_out_count"] >= 1
    assert "RotRiskStar" in build["xi_gated_out"]
    assert "RotRiskStar" not in build["squad_df"].head(11)["web_name"].tolist()
    # Same market with the star nailed on → he anchors the XI.
    m2 = _market(gated_star=False)
    build2 = _build(m2)
    assert "RotRiskStar" in build2["squad_df"].head(11)["web_name"].tolist()


def test_start_rate_gate_can_be_disabled(monkeypatch):
    monkeypatch.setattr(config, "CHIP_WILDCARD_XI_MIN_START_RATE", 0.0)
    build = _build(_market(gated_star=True))
    assert build["xi_gated_out_count"] == 0
    assert "RotRiskStar" in build["squad_df"].head(11)["web_name"].tolist()


def test_unknown_start_rate_is_never_gated():
    m = _market(gated_star=True)
    m = m.drop(columns=["recent_gw_avg_starts", "recent_gw_samples"])
    build = _build(m)
    assert build["xi_gated_out_count"] == 0


def test_attacker_preference_needs_clear_defender_edge_to_go_defender_heavy(monkeypatch):
    """With DEF weighted 0.93 in the XI search, a market where defenders barely
    out-score the marginal midfielder/forward still lands on a 3/4-DEF shape;
    with the preference off (1.0 everywhere) the same market goes 5-DEF."""
    m = _market(defender_uplift=1.05)  # DEF ~4.3-4.8/GW vs cheap MID 3.0 / FWD 2.8
    monkeypatch.setattr(config, "CHIP_WILDCARD_XI_POS_MULT", {"GKP": 1.0, "DEF": 1.0, "MID": 1.0, "FWD": 1.0})
    monkeypatch.setattr(config, "CHIP_WILDCARD_FORMATION_SHORTLIST", 7)
    flat = _build(m)
    monkeypatch.setattr(config, "CHIP_WILDCARD_XI_POS_MULT", {"GKP": 1.0, "DEF": 0.80, "MID": 1.0, "FWD": 1.0})
    pref = _build(m)
    assert flat["formation"][0] >= pref["formation"][0]
    # The reported objective is always the raw score (never the weighted one).
    xi = pref["squad_df"].head(11)
    assert abs(pref["objective_xi_total"] - float(xi["chip_score"].sum())) < 1e-6


def test_injured_never_drafted_anywhere():
    m = _market()
    m.loc[m["web_name"] == "MID0", "status"] = "i"
    m.loc[m["web_name"] == "FodderGK", "status"] = "i"
    build = _build(m)
    names = build["squad_df"]["web_name"].tolist()
    assert "MID0" not in names and "FodderGK" not in names


def test_team_cap_holds_across_xi_and_bench():
    m = _market()
    # Make team 6 (RotDEF_home's team) the best everywhere so the cap binds.
    mask = m["team"] == 6
    m.loc[mask, GW_COLS] = m.loc[mask, GW_COLS] + 3.0
    m.loc[mask, "xpts_horizon"] = m.loc[mask, GW_COLS].sum(axis=1)
    build = _build(m)
    assert build["ok"]
    assert build["squad_df"]["team"].value_counts().max() <= 3


def test_deterministic():
    a = _build(_market())
    b = _build(_market())
    assert a["squad_df"]["id"].tolist() == b["squad_df"]["id"].tolist()


def test_premium_captain_floor_respected_when_affordable():
    build = _build(_market(), min_premium_attackers=1, premium_floor=10.5,
                   premium_positions=["MID", "FWD"])
    xi = build["squad_df"].head(11)
    prem = xi[(xi["pos"].isin(["MID", "FWD"])) & (xi["price_m"] >= 10.5)]
    assert len(prem) >= 1


def test_bench_never_blows_the_budget_when_no_body_sits_under_the_cap():
    """Market whose cheapest keeper/defender costs more than the rotation
    caps: the rotation slots become plain cheapest fodder, never a premium."""
    rows = []
    pid = 1
    for pos, n, price in (("GKP", 2, 5.0), ("DEF", 5, 5.0), ("MID", 5, 5.0), ("FWD", 3, 5.0)):
        for i in range(n):
            rows.append(_row(pid, f"own{pid}", pos, pid % 10, price, [2.0] * 3)); pid += 1
    for pos, n in (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for i in range(n):
            rows.append(_row(pid, f"star{pid}", pos, pid % 10, 15.0, [9.0] * 3)); pid += 1
    m = pd.DataFrame(rows)
    build = _build(m, budget=80.0)
    assert build["ok"], build["reason"]
    assert float(build["squad_df"]["price_m"].sum()) <= 80.0 + 1e-9
    assert float(build["squad_df"].tail(4)["price_m"].max()) <= 5.0


def test_missing_score_column_is_a_clean_failure():
    build = optimizer.build_wildcard_squad(_market(), "nope", 100.0)
    assert build["ok"] is False and build["squad_df"] is None
