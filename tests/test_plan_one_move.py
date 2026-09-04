"""One clear recommendation: at most one move per GW, framed as now-vs-roll."""
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


def _two_upgrade_market():
    # Two starters with two clear upgrades available.
    players = [{"id": 1, "pos": "MID", "xpts": 2.0}, {"id": 2, "pos": "MID", "xpts": 2.0}]
    market = players + [
        {"id": 3, "pos": "MID", "xpts": 9.0},
        {"id": 4, "pos": "MID", "xpts": 8.0},
    ]
    return market


def test_one_move_per_gw_cap():
    plan = tp.plan_transfers(_proj_frame(_two_upgrade_market()), squad_ids=[1, 2],
                             gws=[10, 11], itb_m=0.0, start_ft=2,
                             allow_hits=False, min_gain=2.0, max_moves_per_gw=1)
    for g in plan["plan"]:
        assert len(g["moves"]) <= 1


def test_spend_reasoning_quotes_roll_alternative():
    plan = tp.plan_transfers(_proj_frame(_two_upgrade_market()), squad_ids=[1, 2],
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=False, min_gain=2.0, max_moves_per_gw=1)
    assert plan["verdict"] == "spend"
    assert "roll" in plan["reasoning"].lower()
    assert "vs" in plan["reasoning"].lower() or "beats" in plan["reasoning"].lower()


def test_roll_alternative_is_computed_and_attached():
    plan = tp.plan_transfers(_proj_frame(_two_upgrade_market()), squad_ids=[1, 2],
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=False, min_gain=2.0, max_moves_per_gw=1)
    assert isinstance(plan.get("roll_alternative_net_gain"), float)
    # Same moves started later can't beat starting now in this model.
    assert plan["roll_alternative_net_gain"] <= plan["total_net_gain"] + 1e-9


def test_roll_alternative_gets_to_spend_the_banked_double():
    # Upgrades worth +7/GW each. Spend path: A at GW10 (2 GWs) + B at GW11
    # (1 GW) = 21. Roll path must play BOTH at GW11 (= 14), not be capped to
    # one move like the headline plan — a capped counterfactual undersells
    # rolling.
    players = [{"id": 1, "pos": "MID", "xpts": 2.0}, {"id": 2, "pos": "MID", "xpts": 2.0}]
    market = players + [
        {"id": 3, "pos": "MID", "xpts": 9.0},
        {"id": 4, "pos": "MID", "xpts": 9.0},
    ]
    plan = tp.plan_transfers(_proj_frame(market), squad_ids=[1, 2],
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=False, min_gain=2.0, max_moves_per_gw=1)
    assert plan["total_net_gain"] == 21.0
    assert plan["roll_alternative_net_gain"] == 14.0


def test_reasoning_names_the_counterfactual_double():
    plan = tp.plan_transfers(_proj_frame(_two_upgrade_market()), squad_ids=[1, 2],
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=False, min_gain=2.0, max_moves_per_gw=1)
    assert plan["verdict"] == "spend"
    # The counterfactual's actual moves appear in the reasoning, not just a net.
    assert "->" in plan["reasoning"].split("rolling", 1)[1]


def test_below_bar_still_rolls():
    players = [{"id": 1, "pos": "MID", "xpts": 2.0}]
    market = players + [{"id": 2, "pos": "MID", "xpts": 2.5}]
    plan = tp.plan_transfers(_proj_frame(market), squad_ids=[1],
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=False, min_gain=2.0, max_moves_per_gw=1)
    assert plan["plan"][0]["action"] == "roll"
