import pandas as pd

from src import config
from src.chip_advisor import build_chip_plan, plan_squads_by_gw, score_wildcard
from tests.test_chip_advisor import _squad_15

GWS = [5, 6, 7, 8]


def _market_with_stars():
    own = _squad_15(xpts=2.0)
    stars = _squad_15(prefix="star", xpts=6.0)
    stars["player_id"] = stars["player_id"] + 100
    market = pd.concat([own, stars], ignore_index=True)
    return own, {g: market for g in GWS}


def _move(gw, sell, buy, hit_cost=0.0):
    return {"gw": gw, "hit_cost": hit_cost, "moves": [{"sell": {"id": sell}, "buy": {"id": buy}}]}


def test_plan_squads_follow_moves_in_order():
    start = set(range(1, 16))
    squads = plan_squads_by_gw(start, [_move(9, 3, 30), {"gw": 10, "hit_cost": 0.0, "moves": []}, _move(11, 30, 31)])
    assert 30 in squads[9] and 3 not in squads[9]
    assert 30 in squads[10]
    assert 31 in squads[11] and 30 not in squads[11]
    assert all(len(s) == 15 for s in squads.values())


def test_baseline_is_plan_squad_xi_over_the_window():
    own, proj = _market_with_stars()
    squad = own[["player_id", "name", "pos", "team", "price_m"]]
    stars = set(range(101, 116))
    base = score_wildcard(squad, proj, [5], horizon=4, wc_squads={5: stars})[0].expected_value
    # GW5: sell an own MID (id 8, 2 xPts) for a star MID (id 108, 6 xPts) → +4 a GW over 4 GWs.
    squads = plan_squads_by_gw(set(range(1, 16)), [_move(5, 8, 108)])
    planned = score_wildcard(squad, proj, [5], horizon=4, wc_squads={5: stars}, plan_squads=squads)[0].expected_value
    assert abs((base - planned) - 16.0) < 1e-6
    later = plan_squads_by_gw(set(range(1, 16)), [_move(15, 8, 108)])
    outside = score_wildcard(squad, proj, [5], horizon=4, wc_squads={5: stars}, plan_squads=later)[0].expected_value
    assert abs(outside - base) < 1e-6


def test_hits_inside_the_window_count_against_the_plan():
    own, proj = _market_with_stars()
    squad = own[["player_id", "name", "pos", "team", "price_m"]]
    stars = set(range(101, 116))
    no_hit = plan_squads_by_gw(set(range(1, 16)), [_move(5, 8, 108)])
    hit_plan = [_move(5, 8, 108, hit_cost=4.0)]
    a = score_wildcard(squad, proj, [5], horizon=4, wc_squads={5: stars}, plan_squads=no_hit)[0].expected_value
    b = score_wildcard(squad, proj, [5], horizon=4, wc_squads={5: stars},
                       plan_squads=plan_squads_by_gw(set(range(1, 16)), hit_plan),
                       plan_hits_by_gw={5: 4.0})[0].expected_value
    assert abs((b - a) - 4.0) < 1e-6


def test_wc_squad_from_preset_is_used():
    own, proj = _market_with_stars()
    squad = own[["player_id", "name", "pos", "team", "price_m"]]
    recs = score_wildcard(squad, proj, [5], horizon=4, wc_squads={5: set(range(1, 16))})
    assert recs[0].expected_value == 0.0   # the "wildcard" squad is the one already owned


def test_missing_preset_squad_falls_back_and_says_so():
    own, proj = _market_with_stars()
    squad = own[["player_id", "name", "pos", "team", "price_m"]]
    recs = score_wildcard(squad, proj, [5], horizon=4, wc_squads={6: set(range(101, 116))})
    assert any("preset draft unavailable" in r for r in recs[0].reasoning)


def test_wildcard_nudge_carries_its_window(monkeypatch):
    own, proj = _market_with_stars()
    monkeypatch.setattr(config, "CHIP_PLAN_MIN_EV", {**config.CHIP_PLAN_MIN_EV, "wildcard": 1.0})
    plan = build_chip_plan(
        squad=own[["player_id", "name", "pos", "team", "price_m"]], current_gw=5,
        gw_projections=proj, chips_played=[{"name": c, "event": 1} for c in ("freehit", "bboost", "3xc")],
        horizon_gws=4, wc_squads={g: set(range(101, 116)) for g in GWS},
    )
    assert plan["nudge"]["chip"] == "wildcard"
    assert plan["nudge"]["window_gws"] == [5, 8]


def test_chips_route_nets_against_the_headline_plan_with_preset_squads(monkeypatch):
    import api.chips as chips
    from api import wildcard as wc_module

    own = _squad_15(xpts=2.0)
    proj = pd.DataFrame({"id": list(range(1, 16)), "price_m": [5.0] * 15,
                         **{f"xpts_gw{g}": [2.0] * 15 for g in range(5, 13)}})
    ctx = {"proj": proj, "squad": own[["player_id", "name", "pos", "team", "price_m"]],
           "gw_projections": {g: own for g in range(5, 13)}, "bank_m": 0.5, "free_transfers": 1,
           "teams_short_map": {}}
    monkeypatch.setattr(chips, "_build_context_for_entry", lambda *a, **k: ctx)
    seen = {}

    def fake_plan(proj_df, squad_ids, gws, **kw):
        seen["plan_kwargs"] = kw
        return {"plan": [], "total_net_gain": 0.0}

    monkeypatch.setattr(chips.transfer_planner, "plan_transfers", fake_plan)
    monkeypatch.setattr(chips, "build_chip_signals", lambda *a, **k: {})
    monkeypatch.setattr(chips, "_get_entry_chips", lambda entry_id: [])
    calls = []
    monkeypatch.setattr(wc_module, "preset_squad_ids",
                        lambda proj_all, boot, g, h, budget, name: calls.append((g, h, budget, name)) or {1, 2})
    monkeypatch.setattr("api.main.get_bootstrap_cached", lambda: {"events": [], "elements": []})

    def fake_build(**kw):
        seen["wc_squads"] = kw.get("wc_squads")
        return {}

    monkeypatch.setattr(chips, "build_chip_plan", fake_build)
    chips._build_plan_response(123, 5, 8)
    assert seen["plan_kwargs"]["allow_hits"] is False
    # 5-GW windows that fit inside GW5-12: starts 5..8, Balanced, budget = squad value + bank.
    assert [c[0] for c in calls] == [5, 6, 7, 8]
    assert {c[3] for c in calls} == {"balanced"} and abs(calls[0][2] - 75.5) < 1e-9
    assert set(seen["wc_squads"]) == {5, 6, 7, 8}
