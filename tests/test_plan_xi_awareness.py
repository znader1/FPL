"""XI-awareness: the horizon planner must not spend transfers (or hits) on
bench players unless the incoming player would actually crack the XI."""
import pandas as pd

from src import transfer_planner as tp


def _proj_frame(players, gws=(10, 11)):
    recs = []
    for p in players:
        r = {
            "id": p["id"],
            "web_name": f"P{p['id']}",
            "pos": p["pos"],
            "team_short": p.get("team", f"T{p['id']}"),
            "price_m": p.get("price", 5.0),
            "status": p.get("status", "a"),
            "chance_of_playing_next_round": p.get("chance", 100),
        }
        for g in gws:
            r[f"xpts_gw{g}"] = p["xpts"]
        recs.append(r)
    return pd.DataFrame(recs)


def _squad_12(bench_xpts=1.0):
    """11 solid starters (MIDs/etc at 5.0) + one weak bench MID (id 12)."""
    players = [{"id": i, "pos": "MID", "xpts": 5.0} for i in range(1, 12)]
    players.append({"id": 12, "pos": "MID", "xpts": bench_xpts})
    return players


def test_bench_upgrade_that_stays_on_bench_is_worthless():
    # Buy (4.0) beats the bench seller (1.0) by 3.0 raw — but he'd still sit
    # behind every 5.0 starter, so the swap adds nothing and must not spend.
    market = _squad_12() + [{"id": 13, "pos": "MID", "xpts": 4.0}]
    plan = tp.plan_transfers(_proj_frame(market), squad_ids=list(range(1, 13)),
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=False, min_gain=2.0)
    assert plan["plan"][0]["action"] == "roll"


def test_bench_upgrade_that_cracks_the_xi_spends():
    # Buy (8.0) would displace a 5.0 starter: effective gain (8-5)*2GWs = 6.0
    # clears the bar even though the seller rides the bench.
    market = _squad_12() + [{"id": 13, "pos": "MID", "xpts": 8.0}]
    plan = tp.plan_transfers(_proj_frame(market), squad_ids=list(range(1, 13)),
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=False, min_gain=2.0)
    first = plan["plan"][0]
    assert first["action"] == "transfer"
    assert first["moves"][0]["buy"]["name"] == "P13"


def test_starter_swap_unaffected_by_xi_rule():
    # Selling a starter keeps the plain hz-vs-hz gain.
    players = [{"id": i, "pos": "MID", "xpts": 5.0} for i in range(1, 12)]
    players.append({"id": 12, "pos": "MID", "xpts": 6.0})  # 12-man, all XI-ish
    market = players + [{"id": 13, "pos": "MID", "xpts": 7.0}]
    plan = tp.plan_transfers(_proj_frame(market), squad_ids=list(range(1, 13)),
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=False, min_gain=2.0)
    assert plan["plan"][0]["action"] == "transfer"


def test_spend_reasoning_quotes_net_after_hits():
    # Two strong XI upgrades with 1 FT and hits allowed: reasoning must quote
    # the net figure and name the hit cost, not the raw sum.
    players = [{"id": i, "pos": "MID", "xpts": 2.0} for i in range(1, 12)]
    players.append({"id": 12, "pos": "MID", "xpts": 2.0})
    market = players + [
        {"id": 13, "pos": "MID", "xpts": 9.0},
        {"id": 14, "pos": "MID", "xpts": 9.0},
    ]
    plan = tp.plan_transfers(_proj_frame(market), squad_ids=list(range(1, 13)),
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=True, min_gain=2.0)
    first = plan["plan"][0]
    if first["hits"] > 0:
        assert "net" in plan["reasoning"]
        assert "hit" in plan["reasoning"]
