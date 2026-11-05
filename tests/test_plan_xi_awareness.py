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


def _squad_15(strong_def_xpts=9.0, weak_def_xpts=3.0):
    """A real 15: 2 strong GKP, one strong DEF + four weak, 5 MID, 3 FWD.
    Ranked purely by xPts the top 11 is 2 GKP + 1 DEF + 5 MID + 3 FWD —
    not a legal line-up."""
    players = [{"id": 1, "pos": "GKP", "xpts": 10.0}, {"id": 2, "pos": "GKP", "xpts": 10.0},
               {"id": 3, "pos": "DEF", "xpts": strong_def_xpts}]
    players += [{"id": i, "pos": "DEF", "xpts": weak_def_xpts} for i in range(4, 8)]
    players += [{"id": i, "pos": "MID", "xpts": 8.0} for i in range(8, 13)]
    players += [{"id": i, "pos": "FWD", "xpts": 8.0} for i in range(13, 16)]
    return players


def test_xi_floor_uses_a_legal_formation():
    players = _squad_15()
    info = tp._build_info(_proj_frame(players), [10, 11])
    squad = [p["id"] for p in players]
    hz = {pid: tp._horizon(info, pid, [10, 11]) for pid in squad}
    xi_ids, by_pos, _ = tp._xi_floors(squad, info, hz)
    assert len(xi_ids) == 11
    assert sum(info[p]["pos"] == "GKP" for p in xi_ids) == 1
    assert sum(info[p]["pos"] == "DEF" for p in xi_ids) >= 3
    # The defensive floor is the weakest STARTING defender (3.0 x 2 GWs),
    # not the one strong one.
    assert by_pos["DEF"] == 6.0


def test_second_defender_upgrade_is_credited_when_top11_has_one_defender():
    # A 6.0/GW defender replacing a 3.0/GW one gains 6.0 over two GWs and
    # clears the DEF bar (2.0 x 2.25) — he must not be scored against the
    # 9.0 defender just because the raw top 11 only had room for one DEF.
    players = _squad_15()
    market = players + [{"id": 16, "pos": "DEF", "xpts": 6.0}]
    plan = tp.plan_transfers(_proj_frame(market), squad_ids=[p["id"] for p in players],
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=False, min_gain=2.0)
    first = plan["plan"][0]
    assert first["action"] == "transfer"
    assert first["moves"][0]["buy"]["name"] == "P16"
    assert first["moves"][0]["position"] == "DEF"
