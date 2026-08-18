import pandas as pd

from src import transfer_planner as tp


def _proj(rows, gws=(1, 2, 3)):
    """rows: list of (id, name, pos, team_short, price, xpts_per_gw_value)."""
    recs = []
    for pid, name, pos, team, price, xg in rows:
        r = {"id": pid, "web_name": name, "pos": pos, "team_short": team, "price_m": price}
        for g in gws:
            r[f"xpts_gw{g}"] = xg
        recs.append(r)
    return pd.DataFrame(recs)


GWS = [1, 2, 3]


def test_proposes_obvious_upgrade_at_first_gw():
    proj = _proj([
        (1, "Weak", "MID", "AAA", 5.0, 2.0),    # owned
        (2, "Strong", "MID", "BBB", 5.0, 6.0),  # free, same price, much better
    ])
    out = tp.plan_transfers(proj, [1], GWS, itb_m=0.0, start_ft=1)
    gw1 = out["plan"][0]
    assert gw1["action"] == "transfer"
    m = gw1["moves"][0]
    assert m["sell"]["id"] == 1 and m["buy"]["id"] == 2
    # remaining-horizon gain = (6-2) * 3 GWs = 12
    assert round(m["score_gain"], 1) == 12.0
    assert gw1["free_transfers_after"] == 0


def test_rolls_when_no_upgrade():
    proj = _proj([
        (1, "Best", "MID", "AAA", 5.0, 6.0),   # owned, already the best
        (2, "Worse", "MID", "BBB", 5.0, 2.0),
    ])
    out = tp.plan_transfers(proj, [1], GWS, start_ft=1)
    gw1 = out["plan"][0]
    assert gw1["action"] == "roll"
    assert gw1["free_transfers_before"] == 1
    # rolling banks the FT -> GW2 enters with 2
    assert out["plan"][1]["free_transfers_before"] == 2


def test_hit_taken_only_when_gain_beats_four():
    # one FT; two upgrades. First uses the FT. Second must clear the -4 bar.
    # small second upgrade (per-GW +1 over 3 GWs = +3 < 4) -> NOT taken as a hit.
    proj = _proj([
        (1, "OwnA", "MID", "AAA", 5.0, 2.0),
        (2, "OwnB", "DEF", "AAA", 5.0, 3.0),
        (3, "UpMID", "MID", "BBB", 5.0, 8.0),   # big MID upgrade
        (4, "UpDEF", "DEF", "CCC", 5.0, 4.0),   # small DEF upgrade (+1/gw = +3 horizon)
    ])
    out = tp.plan_transfers(proj, [1, 2], GWS, start_ft=1, allow_hits=True)
    gw1 = out["plan"][0]
    assert len(gw1["moves"]) == 1              # only the FT move; hit not worth it
    assert gw1["hits"] == 0
    assert gw1["moves"][0]["buy"]["id"] == 3   # took the big MID upgrade


def test_hit_taken_when_worth_it():
    proj = _proj([
        (1, "OwnA", "MID", "AAA", 5.0, 2.0),
        (2, "OwnB", "DEF", "AAA", 5.0, 2.0),
        (3, "UpMID", "MID", "BBB", 5.0, 8.0),   # +6/gw -> +18 horizon
        (4, "UpDEF", "DEF", "CCC", 5.0, 7.0),   # +5/gw -> +15 horizon, clears -4
    ])
    out = tp.plan_transfers(proj, [1, 2], GWS, start_ft=1, allow_hits=True)
    gw1 = out["plan"][0]
    assert len(gw1["moves"]) == 2
    assert gw1["hits"] == 1 and gw1["hit_cost"] == 4.0
    assert gw1["net_gain"] == round(gw1["gw_gain"] - 4.0, 2)


def test_budget_respected():
    proj = _proj([
        (1, "Weak", "MID", "AAA", 5.0, 2.0),
        (2, "Pricey", "MID", "BBB", 9.0, 9.0),  # better but unaffordable (bank 0)
    ])
    out = tp.plan_transfers(proj, [1], GWS, itb_m=0.0, start_ft=1)
    assert out["plan"][0]["action"] == "roll"   # can't afford the upgrade


def test_team_limit_blocks_fourth_from_club():
    # 3 strong BBB players (keep) + 1 weak CCC to upgrade. The best buy is BBB,
    # but selling the weak CCC to get it would be a 4th BBB -> illegal. The
    # planner must fall back to the legal AAA upgrade.
    proj = _proj([
        (1, "B1", "MID", "BBB", 5.0, 7.0),
        (2, "B2", "MID", "BBB", 5.0, 7.0),
        (3, "B3", "MID", "BBB", 5.0, 7.0),
        (6, "WeakC", "MID", "CCC", 5.0, 2.0),   # owned, the one to upgrade
        (4, "UpBBB", "MID", "BBB", 5.0, 9.0),   # best buy, but 4th BBB -> illegal
        (5, "UpAAA", "MID", "AAA", 5.0, 6.0),   # legal upgrade
    ])
    out = tp.plan_transfers(proj, [1, 2, 3, 6], GWS, start_ft=1)
    m = out["plan"][0]["moves"][0]
    assert m["sell"]["id"] == 6 and m["buy"]["id"] == 5  # team-legal upgrade
