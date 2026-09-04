"""Penalty-taker uplift in projections; head-to-head hedge nudge in the planner."""
import pandas as pd

from src import transfer_planner as tp
from src.projections import penalty_taker_uplift


def test_penalty_taker_number_one_gets_uplift():
    s = penalty_taker_uplift(pd.Series([1, 2, None]))
    assert s.iloc[0] == 0.45
    assert s.iloc[1] == 0.0
    assert s.iloc[2] == 0.0


def test_penalty_uplift_disabled_by_config(monkeypatch):
    from src import config
    monkeypatch.setattr(config, "PROJ_PENALTY_TAKER_UPLIFT", 0.0, raising=False)
    s = penalty_taker_uplift(pd.Series([1]))
    assert s.iloc[0] == 0.0


def _proj_frame(players, gws=(10, 11)):
    recs = []
    for p in players:
        r = {
            "id": p["id"],
            "web_name": f"P{p['id']}",
            "pos": p["pos"],
            "team_short": p.get("team", f"T{p['id']}"),
            "price_m": p.get("price", 5.0),
            "status": "a",
            "chance_of_playing_next_round": 100,
        }
        for g in gws:
            r[f"xpts_gw{g}"] = p["xpts"]
        recs.append(r)
    return pd.DataFrame(recs)


def test_h2h_conflict_breaks_tie_toward_clean_candidate():
    # Two identical MID buys; buying P3 (team OPP) would face our owned DEF
    # (team DEF) that GW — the planner must prefer the clean P4.
    players = [
        {"id": 1, "pos": "MID", "team": "OWN", "xpts": 2.0},
        {"id": 2, "pos": "DEF", "team": "DEF", "xpts": 5.0},
    ]
    market = players + [
        {"id": 3, "pos": "MID", "team": "OPP", "xpts": 6.0},
        {"id": 4, "pos": "MID", "team": "NEU", "xpts": 6.0},
    ]
    opps = {10: {"OPP": {"DEF"}, "DEF": {"OPP"}}}
    plan = tp.plan_transfers(_proj_frame(market), squad_ids=[1, 2], gws=[10, 11],
                             itb_m=0.0, start_ft=1, allow_hits=False,
                             min_gain=2.0, max_moves_per_gw=1,
                             opponents_by_gw=opps)
    first = plan["plan"][0]
    assert first["action"] == "transfer"
    assert first["moves"][0]["buy"]["name"] == "P4"


def test_h2h_conflict_is_named_when_unavoidable():
    players = [
        {"id": 1, "pos": "MID", "team": "OWN", "xpts": 2.0},
        {"id": 2, "pos": "DEF", "team": "DEF", "xpts": 5.0},
    ]
    market = players + [{"id": 3, "pos": "MID", "team": "OPP", "xpts": 8.0}]
    opps = {10: {"OPP": {"DEF"}, "DEF": {"OPP"}}}
    plan = tp.plan_transfers(_proj_frame(market), squad_ids=[1, 2], gws=[10, 11],
                             itb_m=0.0, start_ft=1, allow_hits=False,
                             min_gain=2.0, max_moves_per_gw=1,
                             opponents_by_gw=opps)
    first = plan["plan"][0]
    assert first["action"] == "transfer"
    assert first["moves"][0]["h2h_conflicts"] == ["P2"]
