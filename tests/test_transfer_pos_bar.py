"""Positional bar: GKP/DEF swaps need a higher gain than min_gain to beat rolling."""
import pandas as pd

from src import transfer_planner as tp


def _player(pid, pos, price=5.0, xpts=0.0, team=None, status="a", chance=100):
    return {
        "id": pid,
        "pos": pos,
        "price_m": price,
        "xpts": xpts,
        "team_short": team or f"T{pid}",
        "status": status,
        "chance": chance,
    }


def _proj_frame(players, gws=(10, 11)):
    recs = []
    for p in players:
        r = {
            "id": p["id"],
            "web_name": f"P{p['id']}",
            "pos": p["pos"],
            "team_short": p["team_short"],
            "price_m": p["price_m"],
            "status": p["status"],
            "chance_of_playing_next_round": p["chance"],
        }
        for g in gws:
            r[f"xpts_gw{g}"] = p["xpts"]
        recs.append(r)
    return pd.DataFrame(recs)


def test_defender_swap_below_positional_bar_rolls():
    # DEF gain of 2.6 clears the raw min_gain (2.0) but not the DEF bar
    # (2.0 x 1.75 = 3.5): the planner must roll, not spend.
    proj = _proj_frame([
        _player(1, "DEF", xpts=1.0),
        _player(2, "DEF", xpts=2.3),  # horizon gain 2.6 over 2 GWs
        _player(3, "MID", xpts=5.0),
    ])
    plan = tp.plan_transfers(proj, squad_ids=[1, 3], gws=[10, 11], itb_m=0.0,
                             start_ft=1, allow_hits=False, min_gain=2.0)
    assert plan["plan"][0]["action"] == "roll"


def test_midfielder_swap_same_gain_still_spends():
    # Same gain on a MID (multiplier 1.0) must still clear the bar and spend.
    proj = _proj_frame([
        _player(1, "MID", xpts=1.0),
        _player(2, "MID", xpts=2.3),
        _player(3, "DEF", xpts=5.0),
    ])
    plan = tp.plan_transfers(proj, squad_ids=[1, 3], gws=[10, 11], itb_m=0.0,
                             start_ft=1, allow_hits=False, min_gain=2.0)
    first = plan["plan"][0]
    assert first["action"] == "transfer"
    assert first["moves"][0]["sell"]["name"] == "P1"


def test_blocked_defender_does_not_mask_passing_midfielder():
    # Best raw swap is a DEF that fails its bar; a slightly smaller MID gain
    # passes its own bar and must still be found.
    proj = _proj_frame([
        _player(1, "DEF", xpts=1.0),
        _player(2, "DEF", xpts=2.5),   # DEF gain 3.0 < 3.5 bar
        _player(3, "MID", xpts=1.0),
        _player(4, "MID", xpts=2.4),   # MID gain 2.8 > 2.0 bar
    ])
    plan = tp.plan_transfers(proj, squad_ids=[1, 3], gws=[10, 11], itb_m=0.0,
                             start_ft=1, allow_hits=False, min_gain=2.0)
    first = plan["plan"][0]
    assert first["action"] == "transfer"
    assert first["moves"][0]["sell"]["name"] == "P3"


def test_injury_forced_defender_sell_bypasses_positional_bar():
    proj = _proj_frame([
        _player(1, "DEF", price=4.0, xpts=0.2, status="i"),
        _player(2, "DEF", price=4.0, xpts=1.0),
    ])
    plan = tp.plan_transfers(proj, squad_ids=[1], gws=[10, 11], itb_m=0.0,
                             start_ft=1, allow_hits=False, min_gain=2.0)
    assert plan["verdict"] == "spend_forced_injury"
