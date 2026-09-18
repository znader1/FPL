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


def test_same_gw_move_never_resells_a_player_it_just_bought():
    """A greedy per-GW move sequence must never sell a player a earlier move
    in the SAME gameweek just bought. Before the fix, the second move's
    seller pool included every currently-owned player -- including one
    bought a moment earlier this GW -- so a non-XI/bench "gain" (which rates
    a buy against a fixed XI floor, not the seller's own value) could rate
    reselling a just-bought player as the best available move, proposing
    e.g. "sell A, buy Grob" then "sell Grob, buy C" as two transfers instead
    of the always-available, identical-value single move "sell A, buy C".

    Squad: 11 non-MID starters (cheap, low value -- never in the running for
    the MID buys below) + two weak bench MID players, X1 and X2. Market: two
    unowned MID upgrades, Grob and P4. With 2 FT and max_moves_per_gw=2, the
    planner should recommend BOTH bench MIDs get upgraded (X1 -> Grob,
    X2 -> P4) -- never a Grob-in-then-out cycle."""
    xi = [_player(i, pos, price=1.0, xpts=1.5)
          for i, pos in enumerate((["GKP"] * 2 + ["DEF"] * 5 + ["FWD"] * 4), start=1)]
    GROB, P4, X1, X2 = 12, 13, 14, 15
    market = [
        _player(GROB, "MID", price=9.0, xpts=4.5),
        _player(P4, "MID", price=8.5, xpts=4.25),
        _player(X1, "MID", price=4.0, xpts=0.5),
        _player(X2, "MID", price=8.5, xpts=0.5),
    ]
    proj = _proj_frame(xi + market, gws=(10, 11), with_status_cols=False)
    squad_ids = [p["id"] for p in xi] + [X1, X2]

    out = tp.plan_transfers(proj, squad_ids, gws=[10, 11], itb_m=5.0, start_ft=2,
                            ft_cap=5, hit_penalty=4.0, allow_hits=False,
                            min_gain=0.5, max_moves_per_gw=2)

    assert out["verdict"] == "spend"
    assert "roll_alternative_net_gain" in out  # the counterfactual still ran

    first_gw = out["plan"][0]
    moves = first_gw["moves"]
    assert len(moves) == 2

    # The invariant: no move's sell id may equal an earlier move's buy id
    # within this same GW.
    buys_so_far = set()
    for m in moves:
        assert m["sell"]["id"] not in buys_so_far
        buys_so_far.add(m["buy"]["id"])

    # Both moves are distinct, real upgrades: two different sellers, two
    # different buys, neither a fake round-trip through the other.
    sells = {m["sell"]["id"] for m in moves}
    buys = {m["buy"]["id"] for m in moves}
    assert sells == {X1, X2}
    assert buys == {GROB, P4}
    assert all(m["score_gain"] > 0 for m in moves)
def test_horizon_floor_is_one_gw_so_the_slider_is_honoured():
    # "1 GW" on the slider must mean this week alone: no hidden 3-GW ranking.
    from src import config
    assert int(getattr(config, "TRANSFER_PLAN_MIN_HORIZON_GWS")) == 1


def test_single_gw_plan_ranks_this_week_and_skips_the_roll_comparison():
    proj = _proj_frame([
        _player(1, "MID", price=5.0, xpts=2.0),
        _player(2, "MID", price=5.0, xpts=7.0),
    ], gws=(10,))
    out = tp.plan_transfers(proj, squad_ids=[1], gws=[10], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "spend"
    d = out["verdict_detail"]
    assert d["horizon"] == {"start_gw": 10, "end_gw": 10, "n": 1}
    assert d["moves"][0]["this_gw_gain"] == d["moves"][0]["horizon_gain"] == 5.0
    assert d["roll_alternative"] is None
    assert "roll_alternative_net_gain" not in out


def test_min_gain_scales_with_the_plan_horizon():
    assert tp.scaled_min_gain(3) == 2.0          # reference horizon unchanged
    assert tp.scaled_min_gain(1) == 0.667
    assert tp.scaled_min_gain(8) == 5.333
    assert tp.scaled_min_gain(0) == 0.667        # degenerate → treated as 1 GW
    assert tp.scaled_min_gain(1, base=0.0) == 0.1
def test_h2h_penalty_prefers_the_clean_alternative():
    # Squad: own GK (team GK1) + a weak MID. Two upgrades: buy 3 faces the own
    # keeper this GW (team OPP plays GK1) and projects 1.0 higher than buy 4,
    # which faces nobody we own. With a 3-pt penalty the clean buy must win.
    proj = _proj_frame([
        _player(1, "GKP", price=4.5, xpts=4.0, team="GK1"),
        _player(2, "MID", price=5.0, xpts=2.0, team="MIDT"),
        _player(3, "MID", price=5.0, xpts=8.0, team="OPP"),
        _player(4, "MID", price=5.0, xpts=7.0, team="OTH"),
    ], gws=(10, 11))
    opps = {10: {"OPP": {"GK1"}, "GK1": {"OPP"}}, 11: {}}
    out = tp.plan_transfers(proj, squad_ids=[1, 2], gws=[10, 11], itb_m=0.0,
                            start_ft=1, min_gain=2.0, opponents_by_gw=opps)
    first = out["plan"][0]
    assert first["action"] == "transfer"
    assert first["moves"][0]["buy"]["id"] == 4
    assert not first["moves"][0].get("h2h_conflicts")
    # And the conflict is what decided it: with the penalty off, 3 wins.
    from src import config
    saved = config.TRANSFER_H2H_CONFLICT_PENALTY
    try:
        config.TRANSFER_H2H_CONFLICT_PENALTY = 0.0
        out0 = tp.plan_transfers(proj, squad_ids=[1, 2], gws=[10, 11], itb_m=0.0,
                                 start_ft=1, min_gain=2.0, opponents_by_gw=opps)
    finally:
        config.TRANSFER_H2H_CONFLICT_PENALTY = saved
    assert out0["plan"][0]["moves"][0]["buy"]["id"] == 3


# --- Injury-priority preference (src/transfer_planner.py, src/config.py) ---
# When two swaps to the same buy tie on raw gain, prefer selling the player
# with availability risk first (TRANSFER_PLAN_INJURED_SELL_BONUS) -- but the
# reported score_gain must stay the honest, bonus-free number either way.

def test_tied_swaps_prefer_selling_the_doubtful_player():
    # 10 MIDs fill the likely XI; Maguire (DEF, fit) is the 11th/weakest XI
    # member (the position floor); Shaw (DEF, doubtful 75%) is on the bench.
    # A DEF buy scores an identical XI-aware gain either way it's sold.
    players = [_player(i, "MID", price=5.0, xpts=5.0) for i in range(1, 11)]
    players.append(_player(11, "DEF", price=5.0, xpts=2.0, status="a"))   # Maguire
    players.append(_player(12, "DEF", price=4.0, xpts=1.0, status="d", chance=75))  # Shaw
    players.append(_player(13, "DEF", price=5.0, xpts=8.0))               # buy target
    proj = _proj_frame(players, gws=(10,))
    squad_ids = list(range(1, 13))

    out_on = tp.plan_transfers(proj, squad_ids, gws=[10], itb_m=1.0, start_ft=1,
                               min_gain=2.0, prioritize_injured=True)
    move_on = out_on["plan"][0]["moves"][0]
    assert move_on["sell"]["id"] == 12   # Shaw (doubtful) sold
    assert move_on["buy"]["id"] == 13
    assert move_on["score_gain"] == 6.0

    out_off = tp.plan_transfers(proj, squad_ids, gws=[10], itb_m=1.0, start_ft=1,
                                min_gain=2.0, prioritize_injured=False)
    move_off = out_off["plan"][0]["moves"][0]
    assert move_off["sell"]["id"] == 11  # Maguire (fit) sold -- raw list order
    assert move_off["buy"]["id"] == 13
    assert move_off["score_gain"] == 6.0  # same reported gain -- bonus never leaks


def test_injured_bonus_wins_small_gap_loses_large_gap():
    # Direct unit test of _best_swap's selection score: an "i" seller (risk
    # 1.0, bonus 1.0 -> +1.0) beats a fit seller whose OWN best swap is only
    # 0.9 better, but loses when that gap grows to 1.2.
    info = {
        1: {"id": 1, "pos": "DEF", "team": "TI", "price": 4.0,
            "status": "i", "chance": None, "avail_risk": 1.0},
        2: {"id": 2, "pos": "DEF", "team": "TF", "price": 4.5,
            "status": "a", "chance": 100, "avail_risk": 0.0},
        3: {"id": 3, "pos": "DEF", "team": "TB3", "price": 4.0},
        4: {"id": 4, "pos": "DEF", "team": "TB4", "price": 4.5},
    }
    hz_small = {1: 0.0, 2: 0.0, 3: 5.0, 4: 5.9}
    best = tp._best_swap({1, 2}, info, [3, 4], hz_small, bank=0.0, team_counts={},
                         injured_bonus=1.0)
    assert best["sell"] == 1 and best["buy"] == 3  # i-seller wins the 0.9 gap

    hz_large = {1: 0.0, 2: 0.0, 3: 5.0, 4: 6.2}
    best2 = tp._best_swap({1, 2}, info, [3, 4], hz_large, bank=0.0, team_counts={},
                          injured_bonus=1.0)
    assert best2["sell"] == 2 and best2["buy"] == 4  # loses the 1.2 gap


def test_sell_availability_present_for_doubtful_absent_for_fit():
    proj_doubt = _proj_frame([
        _player(1, "MID", price=5.0, xpts=2.0, status="d", chance=60),
        _player(2, "MID", price=5.0, xpts=7.0),
    ], gws=(10,))
    out = tp.plan_transfers(proj_doubt, squad_ids=[1], gws=[10], itb_m=0.0,
                            start_ft=1, min_gain=2.0)
    move = out["plan"][0]["moves"][0]
    assert move["sell_availability"] == {"status": "d", "chance": 60.0}

    proj_fit = _proj_frame([
        _player(1, "MID", price=5.0, xpts=2.0),
        _player(2, "MID", price=5.0, xpts=7.0),
    ], gws=(10,))
    out2 = tp.plan_transfers(proj_fit, squad_ids=[1], gws=[10], itb_m=0.0,
                             start_ft=1, min_gain=2.0)
    move2 = out2["plan"][0]["moves"][0]
    assert "sell_availability" not in move2


def test_runner_ups_carry_sell_availability():
    proj = _proj_frame([
        _player(1, "MID", price=5.0, xpts=1.0),                            # sold (big gain)
        _player(2, "DEF", price=4.0, xpts=2.0, status="d", chance=50),     # runner-up, doubtful
        _player(3, "MID", price=5.0, xpts=8.0),                            # buy for seller 1
        _player(4, "DEF", price=4.0, xpts=3.0),                            # buy for seller 2
    ], gws=(10,))
    out = tp.plan_transfers(proj, squad_ids=[1, 2], gws=[10], itb_m=0.0,
                            start_ft=1, min_gain=2.0)
    runner_ups = out["verdict_detail"]["runner_ups"]
    ru = next(r for r in runner_ups if r["sell"]["id"] == 2)
    assert ru["sell_availability"] == {"status": "d", "chance": 50.0}


def test_nan_chance_normalises_to_none_and_stays_json_safe():
    # chance_of_playing_next_round arrives as pandas NaN (missing), not None,
    # for many injured players once mixed into a float64 column alongside a
    # numeric peer -- must normalize to None, never leak NaN into the payload
    # (Starlette's JSONResponse uses allow_nan=False -> ValueError -> 500).
    import json

    proj = _proj_frame([
        _player(1, "MID", price=5.0, xpts=2.0, status="i", chance=None),  # unknown chance -> NaN col
        _player(2, "MID", price=5.0, xpts=7.0),                           # numeric peer, forces float64
    ], gws=(10,))
    out = tp.plan_transfers(proj, squad_ids=[1], gws=[10], itb_m=0.0, start_ft=1, min_gain=2.0)
    move = out["plan"][0]["moves"][0]
    assert move["sell_availability"] == {"status": "i", "chance": None}
    json.dumps(out, allow_nan=False)  # must not raise


def test_avail_risk_known_full_chance_is_no_risk_even_for_doubtful_status():
    # A "d" status with a KNOWN chance of 100 is not a risk -- only an
    # UNKNOWN chance (None) with status "d" defaults to 0.5.
    assert tp._avail_risk("d", 100.0) == 0.0
    assert tp._avail_risk("d", None) == 0.5
    assert tp._avail_risk("d", 75.0) == 0.5
