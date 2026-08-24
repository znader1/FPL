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


def _player(pid, pos, price=5.0, xpts=0.0, team=None, status="a", chance=100):
    """A player spec for _proj_frame. Distinct default team per id keeps the
    3-per-club cap out of the way unless a test cares about it."""
    return {
        "id": pid,
        "pos": pos,
        "price_m": price,
        "xpts": xpts,
        "team_short": team or f"T{pid}",
        "status": status,
        "chance": chance,
    }


def _proj_frame(players, gws=(10, 11), with_status_cols=True):
    """rows: list of _player(...) dicts. Builds xpts_gw{N} columns for `gws`,
    plus status/chance_of_playing_next_round columns unless disabled."""
    recs = []
    for p in players:
        r = {
            "id": p["id"],
            "web_name": f"P{p['id']}",
            "pos": p["pos"],
            "team_short": p["team_short"],
            "price_m": p["price_m"],
        }
        for g in gws:
            r[f"xpts_gw{g}"] = p["xpts"]
        if with_status_cols:
            r["status"] = p["status"]
            r["chance_of_playing_next_round"] = p["chance"]
        recs.append(r)
    return pd.DataFrame(recs)


def test_red_flag_starter_forces_spend_verdict():
    # Squad player with status "i" and a cheap same-position replacement available;
    # replacement gain is BELOW min_gain — the forced sell must happen anyway.
    proj = _proj_frame([
        _player(1, "DEF", price=4.0, xpts=0.2, status="i"),   # injured squad DEF
        _player(2, "DEF", price=4.0, xpts=1.0),               # replacement, gain 0.8 < min_gain 2.0
        _player(3, "MID", price=8.0, xpts=6.0),
    ])
    out = tp.plan_transfers(proj, squad_ids=[1, 3], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "spend_forced_injury"
    first = out["plan"][0]
    assert first["action"] == "transfer"
    assert any(m["sell"]["id"] == 1 for m in first["moves"])
    assert "P1" in out["reasoning"]  # reasoning names the flagged player


def test_red_flag_zero_chance_also_forces():
    proj = _proj_frame([
        _player(1, "DEF", price=4.0, xpts=0.2, status="d", chance=0),
        _player(2, "DEF", price=4.0, xpts=1.0),
    ])
    out = tp.plan_transfers(proj, squad_ids=[1], gws=[10], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "spend_forced_injury"


def test_yellow_doubt_does_not_force():
    proj = _proj_frame([
        _player(1, "DEF", price=4.0, xpts=2.0, status="d", chance=75),
        _player(2, "DEF", price=4.0, xpts=2.5),   # gain 1.0 < min_gain -> roll
    ])
    out = tp.plan_transfers(proj, squad_ids=[1], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "roll"


def test_red_flag_bench_does_not_force():
    # 12 squad players; the red-flagged one has the LOWEST first-GW xpts -> bench (not top-11)
    players = [_player(i, "MID", price=5.0, xpts=4.0 + i * 0.1) for i in range(1, 12)]
    players.append(_player(99, "DEF", price=4.0, xpts=0.1, status="i"))
    players.append(_player(100, "DEF", price=4.0, xpts=0.5))  # weak replacement, gain < min_gain
    proj = _proj_frame(players)
    out = tp.plan_transfers(proj, squad_ids=[p_id for p_id in range(1, 12)] + [99],
                             gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "roll"


def test_verdicts_roll_and_spend_with_reasoning():
    proj_roll = _proj_frame([
        _player(1, "DEF", price=4.0, xpts=3.0),
        _player(2, "DEF", price=4.0, xpts=3.5),   # gain 1.0 < 2.0
    ])
    out = tp.plan_transfers(proj_roll, squad_ids=[1], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "roll"
    assert out["first_gw_ft_before"] == 1 and out["first_gw_ft_after"] == 2
    assert "roll" in out["reasoning"].lower()

    proj_spend = _proj_frame([
        _player(1, "DEF", price=4.0, xpts=1.0),
        _player(2, "DEF", price=4.0, xpts=6.0),   # gain 10.0 > 2.0
    ])
    out = tp.plan_transfers(proj_spend, squad_ids=[1], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "spend"
    assert out["reasoning"]


def test_missing_status_columns_noop():
    # Frames without status/chance columns must not crash and never force
    proj = _proj_frame([_player(1, "DEF", price=4.0, xpts=3.0)], with_status_cols=False)
    out = tp.plan_transfers(proj, squad_ids=[1], gws=[10], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] in ("roll", "spend")


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
