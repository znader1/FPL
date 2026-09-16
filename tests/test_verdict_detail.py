"""verdict_detail: the structured twin of the prose `reasoning`."""
import re

import pandas as pd
import pytest

from src import transfer_planner as tp


def _frame(players, gws=(10, 11)):
    """players: dicts with id, pos, xpts (float or {gw: float}), optional price/team/status/chance."""
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
        xp = p["xpts"]
        for g in gws:
            r[f"xpts_gw{g}"] = xp[g] if isinstance(xp, dict) else xp
        recs.append(r)
    return pd.DataFrame(recs)


def _spend_market():
    return [
        {"id": 1, "pos": "MID", "xpts": 2.0},
        {"id": 2, "pos": "MID", "xpts": 2.0},
        {"id": 3, "pos": "MID", "xpts": 9.0},
        {"id": 4, "pos": "MID", "xpts": 8.0},
    ]


def test_spend_detail_carries_both_gains_and_horizon():
    plan = tp.plan_transfers(_frame(_spend_market()), squad_ids=[1, 2], gws=[10, 11],
                             itb_m=0.0, start_ft=1, allow_hits=False, min_gain=2.0,
                             max_moves_per_gw=1)
    d = plan["verdict_detail"]
    assert d["action"] == "spend"
    assert d["horizon"] == {"start_gw": 10, "end_gw": 11, "n": 2}
    assert d["ft_before"] == 1 and d["ft_after"] == 0
    assert d["threshold"] == 2.0
    assert len(d["moves"]) == 1
    m = d["moves"][0]
    assert m["buy"]["id"] == 3
    assert m["this_gw_gain"] == 7.0          # 9 - 2 in GW10
    assert m["horizon_gain"] == 14.0         # (9+9) - (2+2)
    assert m["forced_injury"] is False
    assert d["this_gw_gain"] == 7.0 and d["horizon_gain"] == 14.0
    assert d["hit_cost"] == 0.0
    assert d["plan_net"] == plan["total_net_gain"]
    assert d["next_move"] is None
    # The counterfactual ran and lost; it is reported, not folded into prose.
    assert d["roll_alternative"] is not None
    assert d["roll_alternative"]["net"] == plan["roll_alternative_net_gain"]
    assert d["roll_alternative"]["gw"] == 11
    assert len(d["roll_alternative"]["moves"]) >= 1
    assert "beats rolling" not in plan["reasoning"]
    assert "threshold" not in plan["reasoning"]
    assert "this GW" in plan["reasoning"] and "GW10-11" in plan["reasoning"]
    assert "+14.0 over GW10-11" in plan["reasoning"]


def test_reasoning_numbers_are_one_decimal():
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "MID", "xpts": 2.13},
        {"id": 2, "pos": "MID", "xpts": 2.13},
        {"id": 3, "pos": "MID", "xpts": 9.07},
        {"id": 4, "pos": "MID", "xpts": 8.01},
    ]), squad_ids=[1, 2], gws=[10, 11], itb_m=0.0, start_ft=1, allow_hits=False,
        min_gain=2.0, max_moves_per_gw=1)
    assert not re.search(r"\d\.\d{2,}", plan["reasoning"]), plan["reasoning"]


def test_roll_detail_when_nothing_clears_the_bar():
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "DEF", "price": 4.0, "xpts": 3.0},
        {"id": 2, "pos": "DEF", "price": 4.0, "xpts": 3.5},
    ]), squad_ids=[1], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    d = plan["verdict_detail"]
    assert d["action"] == "roll"
    assert d["moves"] == []
    assert d["this_gw_gain"] == 0.0 and d["horizon_gain"] == 0.0
    assert d["ft_before"] == 1 and d["ft_after"] == 2
    assert d["roll_alternative"] is None       # no spend to compare against
    assert d["next_move"] is None
    assert "roll" in plan["reasoning"].lower()


def test_roll_detail_names_the_next_planned_move():
    # GW10: buying 2 gains nothing (1 vs 5). GW11: gains 4 -> plan moves then.
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "MID", "xpts": {10: 5.0, 11: 5.0}},
        {"id": 2, "pos": "MID", "xpts": {10: 1.0, 11: 9.0}},
    ]), squad_ids=[1], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    d = plan["verdict_detail"]
    assert d["action"] == "roll"
    assert d["next_move"] is not None
    assert d["next_move"]["gw"] == 11
    assert d["next_move"]["moves"][0]["buy"]["id"] == 2
    assert d["next_move"]["horizon_gain"] == 4.0
    assert "GW11" in plan["reasoning"]


def test_counterfactual_flip_reports_rejected_spend():
    # Spend now: (1+9)-(2+2)=6 at GW10, then +7 at GW11 = 13.
    # Roll: two swaps at GW11 = 7+7 = 14 > 13 -> verdict flips to roll.
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "MID", "xpts": 2.0},
        {"id": 2, "pos": "MID", "xpts": 2.0},
        {"id": 3, "pos": "MID", "xpts": {10: 1.0, 11: 9.0}},
        {"id": 4, "pos": "MID", "xpts": {10: 1.0, 11: 9.0}},
    ]), squad_ids=[1, 2], gws=[10, 11], itb_m=0.0, start_ft=1, allow_hits=False,
        min_gain=2.0, max_moves_per_gw=1)
    assert plan["verdict"] == "roll"
    d = plan["verdict_detail"]
    assert d["action"] == "roll"
    assert d["plan_net"] == 14.0
    assert d["roll_alternative"]["net"] == 13.0
    assert d["roll_alternative"]["gw"] == 10
    assert len(d["roll_alternative"]["moves"]) == 1
    assert d["next_move"]["gw"] == 11
    assert len(d["next_move"]["moves"]) == 2
    assert "roll" in plan["reasoning"].lower()


def test_forced_injury_detail():
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "DEF", "price": 4.0, "xpts": 0.2, "status": "i"},
        {"id": 2, "pos": "DEF", "price": 4.0, "xpts": 1.0},
        {"id": 3, "pos": "MID", "price": 8.0, "xpts": 6.0},
    ]), squad_ids=[1, 3], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    d = plan["verdict_detail"]
    assert d["action"] == "spend_forced_injury"
    assert d["moves"][0]["forced_injury"] is True
    assert d["moves"][0]["sell"]["id"] == 1
    assert d["roll_alternative"] is None       # urgency skips the comparison


def test_runner_ups_other_seller_swap_after_spend():
    # Seller 2's lower price rules out the shared best target (id 3), so its
    # own best swap is a genuinely distinct buy (id 4) -- not a collapse onto
    # the same target as the chosen move.
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "MID", "price": 5.0, "xpts": 2.0},
        {"id": 2, "pos": "MID", "price": 3.0, "xpts": 2.0},
        {"id": 3, "pos": "MID", "price": 5.0, "xpts": 9.0},
        {"id": 4, "pos": "MID", "price": 3.0, "xpts": 7.0},
    ]), squad_ids=[1, 2], gws=[10, 11], itb_m=0.0, start_ft=1, allow_hits=False,
        min_gain=2.0, max_moves_per_gw=1)
    d = plan["verdict_detail"]
    assert d["action"] == "spend"
    chosen = d["moves"][0]
    assert chosen["sell"]["id"] == 1 and chosen["buy"]["id"] == 3
    ru = d["runner_ups"]
    assert len(ru) == 1
    other = ru[0]
    assert other["sell"]["id"] == 2
    assert other["buy"]["id"] == 4
    assert other["buy"]["id"] != chosen["buy"]["id"]      # not the same pick restated
    assert other["clears_bar"] is True
    assert other["horizon_gain"] == 10.0


def test_runner_ups_roll_market_below_bar():
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "DEF", "price": 4.0, "xpts": 3.0},
        {"id": 2, "pos": "DEF", "price": 4.0, "xpts": 3.5},
    ]), squad_ids=[1], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    d = plan["verdict_detail"]
    assert d["action"] == "roll"
    ru = d["runner_ups"]
    assert len(ru) == 1
    r = ru[0]
    assert r["clears_bar"] is False
    assert r["horizon_gain"] < d["threshold"]
    assert r["sell"]["id"] == 1
    assert r["buy"]["id"] == 2


def test_runner_ups_len_at_most_n():
    squad = [{"id": i, "pos": "MID", "xpts": 2.0} for i in range(1, 7)]
    market = squad + [{"id": 11, "pos": "MID", "xpts": 9.0}]
    plan = tp.plan_transfers(_frame(market), squad_ids=list(range(1, 7)), gws=[10, 11],
                             itb_m=0.0, start_ft=1, allow_hits=False, min_gain=2.0,
                             max_moves_per_gw=1)
    d = plan["verdict_detail"]
    assert len(d["runner_ups"]) <= 5


def test_runner_ups_present_after_counterfactual_flip():
    # Same price-gating as test_runner_ups_other_seller_swap_after_spend so
    # the rejected spend plan's runner-ups aren't just the chosen buy again.
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "MID", "price": 5.0, "xpts": 2.0},
        {"id": 2, "pos": "MID", "price": 3.0, "xpts": 2.0},
        {"id": 3, "pos": "MID", "price": 5.0, "xpts": {10: 1.0, 11: 9.0}},
        {"id": 4, "pos": "MID", "price": 3.0, "xpts": {10: 1.0, 11: 9.0}},
    ]), squad_ids=[1, 2], gws=[10, 11], itb_m=0.0, start_ft=1, allow_hits=False,
        min_gain=2.0, max_moves_per_gw=1)
    assert plan["verdict"] == "roll"
    d = plan["verdict_detail"]
    assert "runner_ups" in d
    assert isinstance(d["runner_ups"], list)
    assert len(d["runner_ups"]) >= 1
    assert all(r["buy"]["id"] != 3 for r in d["runner_ups"])  # not the chosen (rejected) buy restated


def test_runner_ups_excludes_negative_gain_seller():
    # Seller 2 owns a 9.0-xpts player; their only same-position, affordable
    # buy is worse (2.0) -- a losing swap is not "also considered". Seller 5
    # (a different position, genuinely positive gain) still shows.
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "DEF", "price": 4.0, "xpts": 1.0},
        {"id": 2, "pos": "MID", "price": 9.0, "xpts": 9.0},
        {"id": 5, "pos": "FWD", "price": 5.0, "xpts": 3.0},
        {"id": 3, "pos": "DEF", "price": 4.0, "xpts": 8.0},
        {"id": 4, "pos": "MID", "price": 5.0, "xpts": 2.0},
        {"id": 6, "pos": "FWD", "price": 5.0, "xpts": 6.0},
    ]), squad_ids=[1, 2, 5], gws=[10, 11], itb_m=0.0, start_ft=1, allow_hits=False,
        min_gain=2.0, max_moves_per_gw=1)
    d = plan["verdict_detail"]
    assert not any(r["sell"]["id"] == 2 for r in d["runner_ups"])
    assert any(r["sell"]["id"] == 5 for r in d["runner_ups"])  # sanity: positive-gain seller still shows


def _min_info(entries):
    """Minimal info dict for unit-testing `_ranked_swaps` directly, bypassing
    `_frame`/`_build_info` (no xg/gws plumbing needed -- `hz` is passed in)."""
    return {
        pid: {"price": p.get("price", 5.0), "team": p.get("team", f"T{pid}"),
              "pos": p.get("pos", "MID")}
        for pid, p in entries.items()
    }


def test_ranked_swaps_dedupes_shared_target_keeps_higher_gain_seller():
    # Two bench-ish sellers whose best buy is the same player (id 99) -- only
    # the higher-gain seller's (20's) candidate should survive.
    info = _min_info({10: {}, 20: {}, 99: {}})
    hz = {10: 2.0, 20: 1.0, 99: 10.0}
    ranked = tp._ranked_swaps({10, 20}, info, [99], hz, 0.0, {}, None, {}, 0.0, 1.0, {}, 5)
    assert len(ranked) == 1
    assert ranked[0]["sell"] == 20      # gain 9 (10-1) beats seller 10's gain 8 (10-2)
    assert ranked[0]["buy"] == 99
    assert ranked[0]["gain"] == 9.0


def test_ranked_swaps_caps_two_per_position():
    # Three DEF sellers, each price-gated to a distinct affordable ceiling so
    # each has its own best target (101/102/103, price == value, ascending)
    # -- plus one MID seller with an exclusive target. Without the position
    # cap all 3 DEF candidates would survive; with it, the weakest is dropped.
    info = _min_info({
        1: {"pos": "DEF", "price": 5.0}, 2: {"pos": "DEF", "price": 6.0},
        3: {"pos": "DEF", "price": 7.0}, 4: {"pos": "MID", "price": 5.0},
        101: {"pos": "DEF", "price": 5.0}, 102: {"pos": "DEF", "price": 6.0},
        103: {"pos": "DEF", "price": 7.0}, 201: {"pos": "MID", "price": 5.0},
    })
    hz = {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 101: 5.0, 102: 6.0, 103: 7.0, 201: 8.0}
    ranked = tp._ranked_swaps({1, 2, 3, 4}, info, [101, 102, 103, 201], hz, 0.0, {},
                              None, {}, 0.0, 1.0, {}, 5)
    positions = [r["pos"] for r in ranked]
    assert positions.count("DEF") <= 2
    assert "MID" in positions
    assert len(ranked) == 3            # the weakest-gain DEF (seller 1, buy 101) is dropped
    assert not any(r["buy"] == 101 for r in ranked)


def test_runner_ups_excludes_buy_equal_to_chosen_move():
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "MID", "price": 5.0, "xpts": 2.0},
        {"id": 2, "pos": "MID", "price": 3.0, "xpts": 2.0},
        {"id": 3, "pos": "MID", "price": 5.0, "xpts": 9.0},
        {"id": 4, "pos": "MID", "price": 3.0, "xpts": 7.0},
    ]), squad_ids=[1, 2], gws=[10, 11], itb_m=0.0, start_ft=1, allow_hits=False,
        min_gain=2.0, max_moves_per_gw=1)
    d = plan["verdict_detail"]
    chosen_buy = d["moves"][0]["buy"]["id"]
    assert d["runner_ups"]                       # sanity: fixture still yields a runner-up
    assert all(r["buy"]["id"] != chosen_buy for r in d["runner_ups"])


def test_runner_ups_skip_first_gw_recursion_key_present_and_empty():
    plan = tp.plan_transfers(_frame(_spend_market()), squad_ids=[1, 2], gws=[10, 11],
                             itb_m=0.0, start_ft=1, allow_hits=False, min_gain=2.0,
                             max_moves_per_gw=1, _skip_first_gw=True)
    d = plan["verdict_detail"]
    assert "runner_ups" in d
    assert d["runner_ups"] == []


def test_hits_detail_quotes_hit_cost():
    players = [{"id": i, "pos": "MID", "xpts": 2.0} for i in range(1, 13)]
    market = players + [
        {"id": 13, "pos": "MID", "xpts": 9.0},
        {"id": 14, "pos": "MID", "xpts": 9.0},
    ]
    plan = tp.plan_transfers(_frame(market), squad_ids=list(range(1, 13)), gws=[10, 11],
                             itb_m=0.0, start_ft=1, allow_hits=True, min_gain=2.0)
    first = plan["plan"][0]
    d = plan["verdict_detail"]
    assert d["hit_cost"] == first["hit_cost"]
    assert d["horizon_gain"] == pytest.approx(first["gw_gain"], abs=0.02)
    assert len(d["moves"]) == len(first["moves"])
    if first["hits"] > 0:
        assert "hit" in plan["reasoning"]
