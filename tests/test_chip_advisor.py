import math

import pandas as pd

from src import config
from src.chip_advisor import chip_windows, team_fixture_counts, _clip_market_xpts


def test_chip_windows_all_available_when_none_played():
    w = chip_windows([], current_gw=5)
    assert set(w) == {"wildcard", "free_hit", "bench_boost", "triple_captain"}
    assert all(v["available"] for v in w.values())
    assert all(v["half"] == 1 and v["expires_gw"] == 19 for v in w.values())


def test_chip_windows_played_chip_unavailable_in_phase():
    played = [{"name": "bboost", "event": 4}]
    w = chip_windows(played, current_gw=6)
    assert w["bench_boost"]["available"] is False
    assert w["wildcard"]["available"] is True


def test_chip_windows_phase1_play_resets_in_phase2():
    played = [{"name": "3xc", "event": 10}]
    w = chip_windows(played, current_gw=25)
    assert w["triple_captain"]["available"] is True
    assert w["triple_captain"]["half"] == 2
    assert w["triple_captain"]["expires_gw"] == 38


def test_chip_windows_current_gw_play_still_counts_as_available():
    # Advising FOR current_gw: a chip logged in current_gw isn't "gone" yet
    # (mirrors the strictly-before rule in the old _derive_chips_remaining).
    played = [{"name": "wildcard", "event": 7}]
    w = chip_windows(played, current_gw=7)
    assert w["wildcard"]["available"] is True


def test_chip_windows_normalizes_fpl_names():
    played = [{"name": "freehit", "event": 3}, {"name": "BBOOST", "event": 4}]
    w = chip_windows(played, current_gw=8)
    assert w["free_hit"]["available"] is False
    assert w["bench_boost"]["available"] is False


def _fixtures(rows):
    return pd.DataFrame(rows, columns=["event", "team_h", "team_a"])


def test_team_fixture_counts_single_and_double():
    fx = _fixtures([
        (12, 1, 2),
        (12, 1, 3),   # team 1 doubles in GW12
        (13, 2, 3),
    ])
    counts = team_fixture_counts(fx, 12)
    assert counts == {1: 2, 2: 1, 3: 1}


def test_team_fixture_counts_blank_gw_team_absent():
    fx = _fixtures([(12, 1, 2)])
    counts = team_fixture_counts(fx, 12)
    assert 3 not in counts
    assert counts.get(3, 0) == 0


def test_team_fixture_counts_empty_fixtures():
    assert team_fixture_counts(pd.DataFrame(columns=["event", "team_h", "team_a"]), 5) == {}


from src.chip_advisor import effective_min_ev


def test_effective_min_ev_full_far_from_expiry():
    # bench_boost base threshold is 10.0; GW5 vs expiry GW19 is outside the ramp
    assert effective_min_ev("bench_boost", target_gw=5, expires_gw=19) == 10.0


def test_effective_min_ev_decays_inside_ramp():
    # ramp is 5 GWs: at 2 GWs left the threshold is base * 2/5
    v = effective_min_ev("bench_boost", target_gw=17, expires_gw=19)
    assert abs(v - 10.0 * 2 / 5) < 1e-9


def test_effective_min_ev_zero_at_expiry_gw():
    assert effective_min_ev("triple_captain", target_gw=19, expires_gw=19) == 0.0


def test_effective_min_ev_monotonic_toward_expiry():
    vals = [effective_min_ev("wildcard", target_gw=g, expires_gw=19) for g in range(13, 20)]
    assert all(a >= b for a, b in zip(vals, vals[1:]))


from src.chip_advisor import score_free_hit, score_wildcard


def _market(players):
    """players: list of (player_id, name, pos, team, price_m, xpts, fixture_count)."""
    return pd.DataFrame(
        players,
        columns=["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"],
    )


def _squad_15(prefix="own", xpts=2.0):
    rows, pid = [], 1
    for pos, n in (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for i in range(n):
            rows.append((pid, f"{prefix}{pid}", pos, f"T{pid % 10}", 5.0, xpts, 1))
            pid += 1
    return _market(rows)


def test_score_wildcard_net_of_transfer_plan_gain():
    squad = _squad_15(xpts=2.0)
    # Market of stars the squad doesn't own: big raw uplift
    stars = _squad_15(prefix="star", xpts=6.0)
    stars["player_id"] = stars["player_id"] + 100
    market = pd.concat([squad[["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"]], stars])
    gw_projections = {5: market, 6: market, 7: market, 8: market}

    raw = score_wildcard(squad[["player_id", "name", "pos", "team", "price_m"]],
                         gw_projections, [5], horizon=4)
    net = score_wildcard(squad[["player_id", "name", "pos", "team", "price_m"]],
                         gw_projections, [5], horizon=4, transfer_plan_net_gain=10.0)
    assert raw and net
    assert abs(raw[0].expected_value - net[0].expected_value - 10.0) < 1e-6


def test_score_wildcard_respects_budget():
    """Mirrors test_score_free_hit_respects_budget: the WC dream-squad build
    must be budget-constrained via the same optimizer bridge FH already uses,
    not the old unbudgeted top-15-in-market proxy (which could draft e.g. a
    whole cluster of one cheap team regardless of price)."""
    squad = _squad_15(xpts=2.0)
    # Unaffordable stars: price 15.0m each, budget only allows the cheap pool
    stars = _squad_15(prefix="star", xpts=9.0)
    stars["player_id"] = stars["player_id"] + 100
    stars["price_m"] = 15.0
    market = pd.concat([squad[["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"]], stars])
    gw_projections = {5: market, 6: market, 7: market, 8: market}

    recs = score_wildcard(squad[["player_id", "name", "pos", "team", "price_m"]],
                          gw_projections, [5], horizon=4, budget_m=80.0)
    # With an 80m budget nothing beats the (identical-cost) squad already owns → no uplift
    assert recs == [] or recs[0].expected_value < 1.0


def test_score_free_hit_respects_budget():
    squad = _squad_15(xpts=2.0)
    # Unaffordable stars: price 15.0m each, budget only allows the cheap pool
    stars = _squad_15(prefix="star", xpts=9.0)
    stars["player_id"] = stars["player_id"] + 100
    stars["price_m"] = 15.0
    market = pd.concat([squad[["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"]], stars])
    gw_projections = {5: market}

    recs = score_free_hit(squad[["player_id", "name", "pos", "team", "price_m"]],
                          gw_projections, [5], budget_m=80.0)
    # With an 80m budget nothing beats the (identical) cheap pool → no uplift
    assert recs == [] or recs[0].expected_value < 1.0


def test_score_free_hit_blank_gate_suppresses_normal_week():
    """FH is a blank-GW tool, not a weekly upgrade button: an ordinary week
    (no squad players blanking) must not clear the bar even with a big raw
    uplift available in the market."""
    squad = _squad_15(xpts=2.0)  # fixture_count=1 for every row -> 0 blanks
    stars = _squad_15(prefix="star", xpts=20.0)
    stars["player_id"] = stars["player_id"] + 100
    market = pd.concat([squad[["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"]], stars])
    gw_projections = {5: market}

    recs = score_free_hit(squad[["player_id", "name", "pos", "team", "price_m"]],
                          gw_projections, [5], budget_m=200.0)
    assert recs == []


def test_score_free_hit_blank_gate_allows_blank_gw():
    """Once >= CHIP_PLAN_FH_MIN_BLANKING squad players blank, the same big
    uplift is allowed through."""
    squad = _squad_15(xpts=2.0)
    squad.loc[squad.index[:3], "fixture_count"] = 0  # 3 squad players blanking
    stars = _squad_15(prefix="star", xpts=20.0)
    stars["player_id"] = stars["player_id"] + 100
    market = pd.concat([squad[["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"]], stars])
    gw_projections = {5: market}

    recs = score_free_hit(squad[["player_id", "name", "pos", "team", "price_m"]],
                          gw_projections, [5], budget_m=200.0)
    assert recs and recs[0].expected_value > 0


from src.chip_advisor import build_chip_plan


def _gw_projections_with_dgw(gws, dgw_gw, dgw_team="T1"):
    """Own squad (cheap) + a market; on dgw_gw players of dgw_team get fixture_count 2 and 2x xpts."""
    out = {}
    for g in gws:
        m = _squad_15(xpts=3.0)
        if g == dgw_gw:
            mask = m["team"] == dgw_team
            m.loc[mask, "fixture_count"] = 2
            m.loc[mask, "xpts"] = 6.0
        out[g] = m
    return out


def test_build_chip_plan_shape_and_keys():
    gws = [5, 6, 7, 8]
    plan = build_chip_plan(
        squad=_squad_15()[["player_id", "name", "pos", "team", "price_m"]],
        current_gw=5,
        gw_projections=_gw_projections_with_dgw(gws, dgw_gw=6),
        chips_played=[],
        horizon_gws=4,
    )
    assert set(plan) >= {"current_gw", "chips_remaining", "horizon_model_gws",
                         "recommendations", "nudge", "transfer_context"}
    assert plan["current_gw"] == 5
    names = {c["name"] for c in plan["chips_remaining"]}
    assert names == {"wildcard", "free_hit", "bench_boost", "triple_captain"}
    for rec in plan["recommendations"]:
        assert set(rec) >= {"chip", "event_id", "ev_gain", "provisional", "reasons", "ev_curve"}


def test_build_chip_plan_played_chip_absent_from_recommendations():
    gws = [5, 6, 7, 8]
    plan = build_chip_plan(
        squad=_squad_15()[["player_id", "name", "pos", "team", "price_m"]],
        current_gw=5,
        gw_projections=_gw_projections_with_dgw(gws, dgw_gw=6),
        chips_played=[{"name": "bboost", "event": 3}],
        horizon_gws=4,
    )
    assert all(r["chip"] != "bench_boost" for r in plan["recommendations"])
    bb = next(c for c in plan["chips_remaining"] if c["name"] == "bench_boost")
    assert bb["available"] is False


def test_build_chip_plan_structural_dgw_beyond_horizon_is_provisional():
    fx = _fixtures([(30, 1, 2), (30, 1, 3)])  # team 1 doubles in GW30, far beyond model zone
    plan = build_chip_plan(
        squad=_squad_15()[["player_id", "name", "pos", "team", "price_m"]],
        current_gw=25,
        gw_projections=_gw_projections_with_dgw([25, 26, 27, 28], dgw_gw=None),
        chips_played=[],
        fixtures=fx,
        horizon_gws=4,
    )
    provisional = [r for r in plan["recommendations"] if r["provisional"]]
    assert any(r["event_id"] == 30 for r in provisional)
    assert all(r["ev_gain"] is None for r in provisional)


def test_build_chip_plan_nudge_only_for_current_gw_above_floor():
    gws = [5, 6, 7, 8]
    plan = build_chip_plan(
        squad=_squad_15()[["player_id", "name", "pos", "team", "price_m"]],
        current_gw=5,
        gw_projections=_gw_projections_with_dgw(gws, dgw_gw=7),
        chips_played=[],
        horizon_gws=4,
    )
    if plan["nudge"] is not None:
        assert plan["nudge"]["event_id"] == 5


from src.utils import normalize_chip_strategy


def test_normalize_chip_strategy_new_chips():
    assert normalize_chip_strategy("bench_boost") == "bench_boost"
    assert normalize_chip_strategy("bboost") == "bench_boost"
    assert normalize_chip_strategy("bb") == "bench_boost"
    assert normalize_chip_strategy("triple_captain") == "triple_captain"
    assert normalize_chip_strategy("3xc") == "triple_captain"
    assert normalize_chip_strategy("tc") == "triple_captain"


def test_normalize_chip_strategy_existing_unchanged():
    assert normalize_chip_strategy("wildcard") == "wildcard"
    assert normalize_chip_strategy("fh") == "free_hit"
    assert normalize_chip_strategy("") == "none"
    assert normalize_chip_strategy("garbage") == "none"


def test_chip_agent_tool_returns_full_plan(monkeypatch):
    from agents import chip_agent

    sentinel = {"recommendations": [], "nudge": None, "chips_remaining": [],
                "current_gw": 5, "horizon_model_gws": 8, "transfer_context": {}}
    monkeypatch.setattr(chip_agent, "build_chip_plan", lambda **kw: sentinel)

    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    result = chip_agent._handle_tool_call(
        "get_chip_recommendations", {"current_gw": 5},
        squad, {5: _squad_15()}, ["wildcard"],
    )
    assert result == sentinel


def test_chip_agent_tool_threads_breaks_to_build_chip_plan(monkeypatch):
    """breaks must reach build_chip_plan (so its confidence haircut / nudge
    flag fire for the chat path too) AND be surfaced directly in the tool
    payload (stringified keys) so the agent can cite it."""
    from agents import chip_agent

    captured = {}

    def fake_build_chip_plan(**kw):
        captured.update(kw)
        return {"recommendations": [], "nudge": None, "chips_remaining": [],
                "current_gw": 5, "horizon_model_gws": 8, "transfer_context": {}}

    monkeypatch.setattr(chip_agent, "build_chip_plan", fake_build_chip_plan)

    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    breaks = {7: {"gap_days": 13.0, "prev_event": 6}}
    result = chip_agent._handle_tool_call(
        "get_chip_recommendations", {"current_gw": 5},
        squad, {5: _squad_15()}, ["wildcard"],
        breaks=breaks,
    )

    assert captured["breaks"] == breaks
    assert result["breaks"] == {"7": {"gap_days": 13.0, "prev_event": 6}}


def test_chip_agent_tool_omits_breaks_key_when_absent(monkeypatch):
    """No breaks known (or upstream detection failed) -> no 'breaks' key,
    matching the prompt's "the context MAY include a breaks map" framing."""
    from agents import chip_agent

    sentinel = {"recommendations": [], "nudge": None, "chips_remaining": [],
                "current_gw": 5, "horizon_model_gws": 8, "transfer_context": {}}
    monkeypatch.setattr(chip_agent, "build_chip_plan", lambda **kw: sentinel)

    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    result = chip_agent._handle_tool_call(
        "get_chip_recommendations", {"current_gw": 5},
        squad, {5: _squad_15()}, ["wildcard"],
    )
    assert "breaks" not in result


def test_orchestrator_threads_chips_played_to_chip_agent(monkeypatch):
    """The orchestrator must not silently treat every chip as available: it
    has to forward the context's chips_played through to run_chip_agent so
    build_chip_plan can derive real availability/expiry."""
    from agents import orchestrator

    captured = {}

    def fake_run_chip_agent(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(orchestrator, "run_chip_agent", fake_run_chip_agent)

    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    already_played = [{"name": "3xc", "event": 2}]
    context = {
        "squad": squad,
        "gw_projections": {5: _squad_15()},
        "chips_remaining": ["wildcard"],
        "chips_played": already_played,
    }
    result = orchestrator._handle_tool_call("ask_chip_agent", {"current_gw": 5}, context)

    assert result == "ok"
    assert captured["chips_played"] == already_played


def test_clip_position_aware_caps():
    market = pd.DataFrame({
        "player_id": [1, 2, 3, 4],
        "pos": ["GKP", "DEF", "MID", "FWD"],
        "xpts": [13.5, 11.0, 11.5, 12.5],
    })
    out = _clip_market_xpts(market)
    got = dict(zip(out["player_id"], out["xpts"]))
    assert got[1] == 7.0     # cheap-GKP outlier capped hard
    assert got[2] == 8.0     # DEF spike capped
    assert got[3] == 11.5    # premium MID survives under 12.0 cap
    assert got[4] == 12.5    # premium FWD survives under 13.0 cap


def test_clip_flat_fallback_without_pos_column():
    market = pd.DataFrame({"player_id": [1, 2], "xpts": [13.5, 5.0]})
    out = _clip_market_xpts(market)
    assert out["xpts"].tolist() == [9.0, 5.0]


def test_clip_unknown_pos_uses_flat_clamp():
    market = pd.DataFrame({"player_id": [1], "pos": ["???"], "xpts": [12.0]})
    out = _clip_market_xpts(market)
    assert out["xpts"].tolist() == [9.0]


# ---------------------------------------------------------------------------
# Task 4: new signals threaded through the chip engine
#
# NOTE: the brief's shared builder is named `_squad_15(team="Arsenal")`, which
# would clobber the existing `_squad_15(prefix="own", xpts=2.0)` defined above
# in this same module (Python resolves the module-level name at call time, so
# every earlier test calling `_squad_15(prefix=..., xpts=...)` would break).
# Renamed to `_squad_15_single_team` here; all new call sites below use the
# renamed helper.
# ---------------------------------------------------------------------------

from src.chip_advisor import (
    build_chip_plan, score_free_hit, score_triple_captain, recommend_chips,
)


def _squad_15_single_team(team="Arsenal"):
    """Minimal legal 15: 2 GKP / 5 DEF / 5 MID / 3 FWD, one team name."""
    pos = ["GKP"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return pd.DataFrame({
        "player_id": range(1, 16),
        "name": [f"P{i}" for i in range(1, 16)],
        "pos": pos,
        "team": [team] * 15,
        "price_m": [5.0] * 15,
    })


def _market_for(squad, gw_xpts=4.0, fixture_count=1, extra_rows=40):
    """Market containing the squad plus a filler pool of outside players."""
    rows = squad.copy()
    rows["xpts"] = gw_xpts
    rows["fixture_count"] = fixture_count
    pool_pos = (["GKP", "DEF", "MID", "FWD"] * (extra_rows // 4 + 1))[:extra_rows]
    pool = pd.DataFrame({
        "player_id": range(100, 100 + extra_rows),
        "name": [f"M{i}" for i in range(extra_rows)],
        "pos": pool_pos,
        "team": [f"T{i % 8}" for i in range(extra_rows)],
        "price_m": [5.0] * extra_rows,
        "xpts": [6.0] * extra_rows,
        "fixture_count": [1] * extra_rows,
    })
    return pd.concat([rows, pool], ignore_index=True)


# ---- FH tough-pileup gate ----

def test_fh_tough_pileup_opens_gate_without_blanks():
    squad = _squad_15_single_team(team="Arsenal")
    market = _market_for(squad, gw_xpts=2.0)  # squad weak this GW, market strong
    diff = {5: {"Arsenal": 4.5}}              # all 15 face difficulty 4.5
    recs = score_free_hit(squad, {5: market}, [5], budget_m=100.0,
                          team_difficulty_by_gw=diff)
    assert len(recs) == 1
    assert any("difficulty" in r for r in recs[0].reasoning)


def test_fh_gate_still_closed_on_ordinary_week():
    squad = _squad_15_single_team(team="Arsenal")
    market = _market_for(squad, gw_xpts=2.0)
    diff = {5: {"Arsenal": 2.5}}              # easy fixtures — no trigger
    recs = score_free_hit(squad, {5: market}, [5], budget_m=100.0,
                          team_difficulty_by_gw=diff)
    assert recs == []


def test_fh_no_difficulty_map_falls_back_to_blank_gate_only():
    squad = _squad_15_single_team(team="Arsenal")
    market = _market_for(squad, gw_xpts=2.0)
    recs = score_free_hit(squad, {5: market}, [5], budget_m=100.0,
                          team_difficulty_by_gw=None)
    assert recs == []  # no blanks, no map → today's behavior


# ---- TC haul probability ----

def test_tc_haul_prob_poisson_math():
    squad = _squad_15_single_team(team="Arsenal")
    market = _market_for(squad, gw_xpts=6.0)
    xgi = {i: 0.0 for i in range(1, 16)}
    xgi[13] = 0.9  # a FWD; neutral difficulty → lambda = 0.9
    recs = score_triple_captain(squad, {5: market}, [5], xgi_per90=xgi,
                                team_difficulty_by_gw={5: {"Arsenal": 3.0}})
    lam = 0.9
    expected = 1 - math.exp(-lam) * (1 + lam)
    assert recs[0].haul_prob is not None
    assert abs(recs[0].haul_prob - expected) < 1e-6
    assert any("haul" in r for r in recs[0].reasoning)


def test_tc_haul_prob_missing_xgi_omits_field():
    squad = _squad_15_single_team(team="Arsenal")
    market = _market_for(squad, gw_xpts=6.0)
    recs = score_triple_captain(squad, {5: market}, [5])
    assert recs[0].haul_prob is None
    assert "haul_prob" not in recs[0].to_dict()


def test_tc_haul_prob_dgw_sums_lambdas():
    squad = _squad_15_single_team(team="Arsenal")
    market = _market_for(squad, gw_xpts=6.0, fixture_count=2)
    xgi = {13: 0.9}
    recs = score_triple_captain(squad, {5: market}, [5], xgi_per90=xgi,
                                team_difficulty_by_gw={5: {"Arsenal": 3.0}})
    lam = 0.9 * 2
    expected = 1 - math.exp(-lam) * (1 + lam)
    assert abs(recs[0].haul_prob - expected) < 1e-6


# ---- break haircut + nudge flag ----

def test_break_haircut_and_reason_applied():
    squad = _squad_15_single_team(team="Arsenal")
    market = _market_for(squad, gw_xpts=6.0)
    base = recommend_chips(squad, 5, {5: market}, ["triple_captain"], gws_ahead=0)
    hair = recommend_chips(squad, 5, {5: market}, ["triple_captain"], gws_ahead=0,
                           breaks={5: {"gap_days": 14.0, "prev_event": 4}})
    assert hair[0].confidence < base[0].confidence
    assert abs(hair[0].confidence - base[0].confidence * 0.85) < 1e-6
    assert any("international break" in r for r in hair[0].reasoning)


def test_nudge_wait_for_team_news_flag(monkeypatch):
    squad = _squad_15_single_team(team="Arsenal")
    market = _market_for(squad, gw_xpts=8.0)
    # Force TC over the min-EV bar for a current-GW nudge
    monkeypatch.setattr(config, "CHIP_PLAN_MIN_EV",
                        {**config.CHIP_PLAN_MIN_EV, "triple_captain": 1.0})
    plan_no_break = build_chip_plan(
        squad, 5, {5: market}, chips_played=[], breaks={})
    plan_break = build_chip_plan(
        squad, 5, {5: market}, chips_played=[],
        breaks={5: {"gap_days": 14.0, "prev_event": 4}})
    assert plan_no_break["nudge"]["wait_for_team_news"] is False
    assert plan_break["nudge"]["wait_for_team_news"] is True


# ---- swing reasons ----

def test_wildcard_rec_names_easier_swings(monkeypatch):
    squad = _squad_15_single_team(team="Arsenal")
    markets = {g: _market_for(squad, gw_xpts=2.0) for g in range(5, 9)}
    monkeypatch.setattr(config, "CHIP_PLAN_MIN_EV",
                        {**config.CHIP_PLAN_MIN_EV, "wildcard": 1.0})
    swings = [{"team": "T1", "team_short": "T1", "gw": 5, "delta": 1.2,
               "direction": "easier"}]
    plan = build_chip_plan(squad, 5, markets, chips_played=[], swings=swings)
    wc = next((r for r in plan["recommendations"] if r["chip"] == "wildcard"), None)
    assert wc is not None
    assert any("swing" in reason.lower() for reason in wc["reasons"])


def test_tc_swing_reason_filtered_to_captain_team(monkeypatch):
    """A TC rec should only cite a fixture swing when the swing's team is the
    recommended captain's own team — a swing elsewhere in the league is not
    a reason to triple-captain this player."""
    squad = _squad_15_single_team(team="Arsenal")
    market = _market_for(squad, gw_xpts=8.0)
    monkeypatch.setattr(config, "CHIP_PLAN_MIN_EV",
                        {**config.CHIP_PLAN_MIN_EV, "triple_captain": 1.0})

    swings_other_team = [{"team": "Chelsea", "team_short": "CHE", "gw": 5,
                           "delta": 1.2, "direction": "easier"}]
    plan_other = build_chip_plan(squad, 5, {5: market}, chips_played=[],
                                 swings=swings_other_team)
    tc_other = next(r for r in plan_other["recommendations"] if r["chip"] == "triple_captain")
    assert not any("swing" in reason.lower() for reason in tc_other["reasons"])

    swings_captain_team = [{"team": "Arsenal", "team_short": "ARS", "gw": 5,
                             "delta": 1.2, "direction": "easier"}]
    plan_captain = build_chip_plan(squad, 5, {5: market}, chips_played=[],
                                   swings=swings_captain_team)
    tc_captain = next(r for r in plan_captain["recommendations"] if r["chip"] == "triple_captain")
    assert any("swing" in reason.lower() for reason in tc_captain["reasons"])


# ---- confidence surfaced in the rec payload (finding 1) ----

def test_build_chip_plan_confidence_key_and_break_haircut(monkeypatch):
    """The rec dict must carry a `confidence` key (so `agents/chip_agent.md`'s
    "confidence >= 0.6" gating step has a field to read), and a break haircut
    on the underlying ChipRecommendation must lower it."""
    squad = _squad_15_single_team(team="Arsenal")
    market = _market_for(squad, gw_xpts=8.0)
    monkeypatch.setattr(config, "CHIP_PLAN_MIN_EV",
                        {**config.CHIP_PLAN_MIN_EV, "triple_captain": 1.0})

    plan_no_break = build_chip_plan(squad, 5, {5: market}, chips_played=[], breaks={})
    plan_break = build_chip_plan(
        squad, 5, {5: market}, chips_played=[],
        breaks={5: {"gap_days": 14.0, "prev_event": 4}})

    tc_no_break = next(r for r in plan_no_break["recommendations"] if r["chip"] == "triple_captain")
    tc_break = next(r for r in plan_break["recommendations"] if r["chip"] == "triple_captain")

    assert "confidence" in tc_no_break
    assert "confidence" in tc_break
    assert tc_break["confidence"] < tc_no_break["confidence"]
    assert abs(tc_break["confidence"] - round(tc_no_break["confidence"] * 0.85, 2)) < 1e-6


# ---- chip outlook (always-visible planning rows) ----

def test_build_chip_plan_outlook_lists_every_available_chip():
    squad = _squad_15_single_team()
    market = _market_for(squad, gw_xpts=6.0)
    plan = build_chip_plan(squad, 5, {5: market}, chips_played=[])
    chips = {o["chip"] for o in plan["outlook"]}
    assert chips == {"wildcard", "free_hit", "bench_boost", "triple_captain"}

    tc = next(o for o in plan["outlook"] if o["chip"] == "triple_captain")
    assert tc["status"] == "hold"
    assert tc["ev_gain"] is not None and tc["ev_gain"] < tc["bar"]
    assert tc["event_id"] == 5
    assert tc["reasons"]

    fh = next(o for o in plan["outlook"] if o["chip"] == "free_hit")
    assert fh["status"] == "hold"
    assert fh["event_id"] is None  # gate never opened — no candidate window
    assert fh["reasons"]


def test_build_chip_plan_outlook_play_row_matches_recommendation(monkeypatch):
    squad = _squad_15_single_team()
    market = _market_for(squad, gw_xpts=8.0)
    monkeypatch.setattr(config, "CHIP_PLAN_MIN_EV",
                        {**config.CHIP_PLAN_MIN_EV, "triple_captain": 1.0})
    plan = build_chip_plan(squad, 5, {5: market}, chips_played=[])
    tc_out = next(o for o in plan["outlook"] if o["chip"] == "triple_captain")
    tc_rec = next(r for r in plan["recommendations"] if r["chip"] == "triple_captain")
    assert tc_out["status"] == "play"
    assert tc_out["event_id"] == tc_rec["event_id"]
    assert tc_out["ev_gain"] == tc_rec["ev_gain"]


def test_build_chip_plan_outlook_excludes_used_chips():
    squad = _squad_15_single_team()
    market = _market_for(squad, gw_xpts=6.0)
    plan = build_chip_plan(squad, 5, {5: market},
                           chips_played=[{"name": "bboost", "event": 3}])
    chips = {o["chip"] for o in plan["outlook"]}
    assert "bench_boost" not in chips


# ---------- 2026-09-17: European weeks, per-GW distributions, calendar ----------

from src.chip_advisor import score_bench_boost, score_triple_captain


def _priors_for(squad_df, p_appear=0.95, xg90=0.4, xa90=0.2):
    return {
        int(pid): {"pos": pos, "xg90": xg90, "xa90": xa90, "p_appear": p_appear, "p_60": p_appear * 0.86}
        for pid, pos in zip(squad_df["player_id"], squad_df["pos"])
    }


def test_tc_captain_in_european_week_gets_risk_and_confidence_haircut():
    market = _squad_15(xpts=3.0)
    market.loc[market["player_id"] == 13, "xpts"] = 12.0     # FWD, team T3
    squad = market[["player_id", "name", "pos", "team", "price_m"]]
    plain = score_triple_captain(squad, {5: market}, [5])[0]
    euro = {5: {"T3": {"competition": "ucl", "label": "MD1", "when": "before", "days_before": 3}}}
    hit = score_triple_captain(squad, {5: market}, [5], euro_by_gw=euro)[0]
    assert hit.expected_value == plain.expected_value          # EV untouched at the scorer
    assert hit.confidence < plain.confidence
    assert any("Champions League" in r and "3 days before GW5" in r for r in hit.risks)
    # a different team in Europe doesn't touch the captain
    other = score_triple_captain(squad, {5: market}, [5], euro_by_gw={5: {"T9": {"competition": "ucl", "when": "after"}}})[0]
    assert other.confidence == plain.confidence


def test_tc_distribution_attached_only_with_priors():
    market = _squad_15(xpts=3.0)
    market.loc[market["player_id"] == 13, "xpts"] = 12.0
    squad = market[["player_id", "name", "pos", "team", "price_m"]]
    no = score_triple_captain(squad, {5: market}, [5])[0]
    assert no.pmf is None
    yes = score_triple_captain(squad, {5: market}, [5], player_priors=_priors_for(market))[0]
    assert yes.pmf is not None and abs(yes.pmf.sum() - 1.0) < 1e-9
    assert any("chance the captain returns" in r for r in yes.reasoning)


def test_bb_bench_in_european_weeks_names_players_and_cuts_confidence():
    market = _squad_15(xpts=3.0)
    squad = market[["player_id", "name", "pos", "team", "price_m"]]
    plain = score_bench_boost(squad, {5: market}, [5])[0]
    # every team in Europe → all 4 bench players exposed
    euro = {5: {t: {"competition": "uel", "when": "after"} for t in market["team"].unique()}}
    hit = score_bench_boost(squad, {5: market}, [5], euro_by_gw=euro)[0]
    assert hit.confidence < plain.confidence
    assert any("of your bench 4 are in European weeks" in r for r in hit.risks)
    assert any("15/15 squad players in European weeks" in r for r in hit.reasoning)


def test_bb_distribution_is_bench_convolution():
    market = _squad_15(xpts=3.0)
    squad = market[["player_id", "name", "pos", "team", "price_m"]]
    rec = score_bench_boost(squad, {5: market}, [5], player_priors=_priors_for(market))[0]
    assert rec.pmf is not None
    from src import chip_distribution
    d = chip_distribution.summarize(rec.pmf)
    # four ~3 xPts players: the sum's most likely value sits well above one player's
    assert d["mean"] > 6.0
    assert any("Bench most likely" in r for r in rec.reasoning)


def test_build_chip_plan_applies_european_discount_to_both_sides(monkeypatch):
    monkeypatch.setattr(config, "CHIP_PLAN_EURO_XPTS_MULT", 0.5)
    gws = [5, 6, 7, 8]
    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    base = build_chip_plan(squad=squad, current_gw=5,
                           gw_projections=_gw_projections_with_dgw(gws, dgw_gw=6),
                           chips_played=[], horizon_gws=4)
    euro = {g: {t: {"competition": "ucl", "when": "before"} for t in squad["team"].unique()} for g in gws}
    cut = build_chip_plan(squad=squad, current_gw=5,
                          gw_projections=_gw_projections_with_dgw(gws, dgw_gw=6),
                          chips_played=[], horizon_gws=4, euro_by_gw=euro)
    tc_base = next(o for o in base["outlook"] if o["chip"] == "triple_captain")
    tc_cut = next(o for o in cut["outlook"] if o["chip"] == "triple_captain")
    assert abs(tc_cut["ev_gain"] - 0.5 * tc_base["ev_gain"]) < 1e-6
    assert cut["signals"]["european_calendar"] is True
    assert cut["signals"]["european_xpts_mult"] == 0.5
    assert base["signals"]["european_calendar"] is False


def test_build_chip_plan_distribution_and_curve_probabilities():
    gws = [5, 6, 7, 8]
    projections = _gw_projections_with_dgw(gws, dgw_gw=6)
    for g in gws:
        projections[g].loc[projections[g]["player_id"] == 13, "xpts"] = 16.0
    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    plan = build_chip_plan(squad=squad, current_gw=5, gw_projections=projections,
                           chips_played=[], horizon_gws=4,
                           player_priors=_priors_for(projections[5]),
                           breaks={6: {"gap_days": 14.0, "prev_event": 5}},
                           euro_by_gw={7: {"T3": {"competition": "ucl", "when": "after"}}})
    tc = next(r for r in plan["recommendations"] if r["chip"] == "triple_captain")
    d = tc["distribution"]
    assert {"mean", "modal", "p_return", "p_haul", "p_blank", "p80_low", "p80_high", "bar", "p_beats_bar"} <= set(d)
    assert 0.0 <= d["p_beats_bar"] <= 1.0
    assert d["bar"] == tc_bar(plan, "triple_captain", tc["event_id"])
    by_gw = {p["gw"]: p for p in tc["ev_curve"]}
    assert all("p_beats_bar" in p for p in by_gw.values())
    assert by_gw[6]["post_break"] is True and "post_break" not in by_gw[5]
    assert by_gw[7]["european"] == 2 and "european" not in by_gw[5]   # own3 + own13 are T3
    outlook = next(o for o in plan["outlook"] if o["chip"] == "triple_captain")
    assert outlook["distribution"] == d
    if plan["nudge"] and plan["nudge"]["chip"] == "triple_captain":
        assert plan["nudge"]["p_beats_bar"] == d["p_beats_bar"]
    assert plan["signals"]["distributions"] is True


def test_tc_p_beats_bar_is_measured_on_the_pmf_axis():
    """F2: the pmf excludes the continuous share, so the bar must be scaled too."""
    import numpy as np
    from src import chip_distribution
    gws = [5, 6, 7, 8]
    projections = _gw_projections_with_dgw(gws, dgw_gw=6)
    for g in gws:
        projections[g].loc[projections[g]["player_id"] == 13, "xpts"] = 16.0
    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    priors = _priors_for(projections[5])
    plan = build_chip_plan(squad=squad, current_gw=5, gw_projections=projections,
                           chips_played=[], horizon_gws=4, player_priors=priors)
    tc = next(r for r in plan["recommendations"] if r["chip"] == "triple_captain")
    rec = next(r for r in score_triple_captain(squad, projections, [tc["event_id"]],
                                               player_priors=priors))
    bar = tc["distribution"]["bar"]
    assert bar > 0
    share = chip_distribution.continuous_share([("FWD", 16.0)])
    assert share > 0
    on_axis = round(float(rec.pmf[int(np.ceil(bar * (1 - share))):].sum()), 3)
    naive = round(float(rec.pmf[int(np.ceil(bar)):].sum()), 3)
    assert tc["distribution"]["p_beats_bar"] == on_axis
    assert on_axis > naive                       # the old number understated the odds


def test_bb_payload_drops_per_player_thresholds_while_tc_keeps_them():
    """F3: 6/10/2 describe one player; on a bench-4 sum they carry no signal."""
    gws = [5, 6, 7, 8]
    projections = _gw_projections_with_dgw(gws, dgw_gw=6)
    for g in gws:
        projections[g].loc[projections[g]["player_id"] == 13, "xpts"] = 16.0
    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    plan = build_chip_plan(squad=squad, current_gw=5, gw_projections=projections,
                           chips_played=[], horizon_gws=4,
                           player_priors=_priors_for(projections[5]))
    bb = next(o for o in plan["outlook"] if o["chip"] == "bench_boost")
    d = bb["distribution"]
    assert {"mean", "modal", "p80_low", "p80_high", "bar", "p_beats_bar"} <= set(d)
    assert not ({"p_return", "p_haul", "p_blank"} & set(d))
    assert d["modal"] < 30                       # F1: not the folded ceiling
    tc = next(o for o in plan["outlook"] if o["chip"] == "triple_captain")
    assert {"p_return", "p_haul", "p_blank"} <= set(tc["distribution"])
    # the BB EV curve carries odds but no per-player return rate
    bb_rec = next((r for r in plan["recommendations"] if r["chip"] == "bench_boost"), None)
    if bb_rec is not None:
        assert all("p_return" not in p for p in bb_rec["ev_curve"])
        assert any("p_beats_bar" in p for p in bb_rec["ev_curve"])


def tc_bar(plan, chip, gw):
    expires = next(c["expires_gw"] for c in plan["chips_remaining"] if c["name"] == chip)
    return round(effective_min_ev(chip, gw, expires), 2)


def _events_from(current_gw, n, start="2026-09-12T10:00:00Z"):
    base = pd.Timestamp(start)
    return [{"id": current_gw + i, "deadline_time": (base + pd.Timedelta(days=7 * i)).isoformat()}
            for i in range(n)]


def test_build_chip_plan_calendar_rows():
    gws = [5, 6, 7, 8]
    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    fx = _fixtures([(g, h, a) for g in range(5, 11) for h, a in ((1, 2), (3, 4))] + [(9, 1, 3)])
    labels = {1: "T1", 2: "T2", 3: "T3", 4: "T4", 5: "T5"}
    plan = build_chip_plan(
        squad=squad, current_gw=5, gw_projections=_gw_projections_with_dgw(gws, dgw_gw=None),
        chips_played=[], fixtures=fx, horizon_gws=4,
        events=_events_from(5, 6), team_labels=labels,
        breaks={7: {"gap_days": 14.0, "prev_event": 6}},
        euro_by_gw={6: {"T1": {"competition": "ucl", "label": "MD2", "when": "after"}}},
        cup_clashes={8: {"competition": "fa_cup", "label": "QF", "likely_blank": True}},
    )
    cal = {r["gw"]: r for r in plan["calendar"]}
    assert min(cal) == 5 and max(cal) == 38
    assert cal[5]["in_model_zone"] is True and cal[9]["in_model_zone"] is False
    assert cal[5]["deadline_utc"] is not None and cal[38]["deadline_utc"] is None
    assert cal[7]["post_break"] is True and cal[7]["break_gap_days"] == 14.0
    assert cal[6]["european"] == {"ucl": ["T1"]}
    assert [p["name"] for p in cal[6]["squad_european"]] == ["own1", "own11"]
    assert cal[9]["has_dgw"] is True and cal[9]["dgw_teams"] == ["T1", "T3"]
    assert cal[5]["blank_teams"] == ["T5"]
    assert cal[5]["is_blank_heavy"] is True           # 4 of 5 teams playing <= threshold 14
    assert cal[8]["cup_clash"] == {"competition": "fa_cup", "label": "QF", "likely_blank": True}
    assert cal[20]["n_teams_playing"] is None         # no fixtures known that far


def test_build_chip_plan_cup_clash_becomes_likelihood_tagged_fh_window():
    gws = [5, 6, 7, 8]
    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    # 20 teams play every GW through GW30 — nothing announced, no structural blank
    fx = _fixtures([(g, h, h + 10) for g in range(5, 31) for h in range(1, 11)])
    plan = build_chip_plan(
        squad=squad, current_gw=5, gw_projections=_gw_projections_with_dgw(gws, dgw_gw=None),
        chips_played=[], fixtures=fx, horizon_gws=4,
        cup_clashes={6: {"competition": "fa_cup", "label": "R5", "likely_blank": True},   # inside model zone: ignored
                     12: {"competition": "fa_cup", "label": "QF", "likely_blank": False},  # not a blank-maker
                     15: {"competition": "fa_cup", "label": "QF", "likely_blank": True}},
    )
    fh = [r for r in plan["recommendations"] if r["chip"] == "free_hit"]
    assert len(fh) == 1 and fh[0]["provisional"] is True and fh[0]["event_id"] == 15
    assert fh[0]["likelihood"] == config.CHIP_PLAN_CUP_CLASH_BLANK_PROB
    assert "FA CUP QF" in fh[0]["reasons"][0] and "hold Free Hit" in fh[0]["reasons"][0]


def test_build_chip_plan_cup_clash_skips_when_blank_already_announced_or_chip_used():
    gws = [5, 6, 7, 8]
    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    # GW15 announced with only 4 teams → structural blank rec takes precedence (likelihood 1.0)
    fx = _fixtures([(g, h, h + 10) for g in range(5, 31) if g != 15 for h in range(1, 11)]
                   + [(15, 1, 2), (15, 3, 4)])
    plan = build_chip_plan(
        squad=squad, current_gw=5, gw_projections=_gw_projections_with_dgw(gws, dgw_gw=None),
        chips_played=[], fixtures=fx, horizon_gws=4,
        cup_clashes={15: {"competition": "fa_cup", "label": "QF", "likely_blank": True}},
    )
    fh = [r for r in plan["recommendations"] if r["chip"] == "free_hit"]
    assert len(fh) == 1 and fh[0]["likelihood"] == 1.0
    used = build_chip_plan(
        squad=squad, current_gw=5, gw_projections=_gw_projections_with_dgw(gws, dgw_gw=None),
        chips_played=[{"name": "freehit", "event": 3}], fixtures=fx, horizon_gws=4,
        cup_clashes={15: {"competition": "fa_cup", "label": "QF", "likely_blank": True}},
    )
    assert not [r for r in used["recommendations"] if r["chip"] == "free_hit"]


# ---------- 2026-09-17: plain-language chip guidance ----------

def test_outlook_guidance_hold_no_window():
    """No candidate window at all -> generic hold + season prior. No p-beats-bar
    clause, no wildcard/free_hit bonus sentence attached."""
    squad = _squad_15_single_team()
    market = _market_for(squad, gw_xpts=6.0)
    plan = build_chip_plan(squad, 5, {5: market}, chips_played=[])
    wc = next(o for o in plan["outlook"] if o["chip"] == "wildcard")
    fh = next(o for o in plan["outlook"] if o["chip"] == "free_hit")
    assert wc["event_id"] is None and fh["event_id"] is None
    assert wc["guidance"] == (
        f"Hold. Nothing in the next {plan['horizon_model_gws']} GWs beats keeping it. "
        f"Best use: {config.CHIP_PLAN_SEASON_PRIORS['wildcard']}."
    )
    assert fh["guidance"] == (
        f"Hold. Nothing in the next {plan['horizon_model_gws']} GWs beats keeping it. "
        f"Best use: {config.CHIP_PLAN_SEASON_PRIORS['free_hit']}."
    )


def test_outlook_guidance_hold_no_window_wildcard_names_transfer_plan():
    """Wildcard-only addendum: when the transfer plan already has positive net
    gain, the hold-no-window sentence names it."""
    squad = _squad_15_single_team()
    market = _market_for(squad, gw_xpts=6.0)
    plan = build_chip_plan(squad, 5, {5: market}, chips_played=[],
                           transfer_plan={"total_net_gain": 5.0})
    wc = next(o for o in plan["outlook"] if o["chip"] == "wildcard")
    assert wc["event_id"] is None
    assert wc["guidance"] == (
        f"Hold. Nothing in the next {plan['horizon_model_gws']} GWs beats keeping it. "
        f"Best use: {config.CHIP_PLAN_SEASON_PRIORS['wildcard']}. "
        "Your squad plus free transfers already covers this stretch."
    )
    # free_hit gets no such addendum even with the same transfer plan
    fh = next(o for o in plan["outlook"] if o["chip"] == "free_hit")
    assert "free transfers" not in fh["guidance"]


def test_outlook_guidance_hold_below_bar_without_distribution():
    squad = _squad_15_single_team()
    market = _market_for(squad, gw_xpts=6.0)
    plan = build_chip_plan(squad, 5, {5: market}, chips_played=[])
    tc = next(o for o in plan["outlook"] if o["chip"] == "triple_captain")
    assert tc["status"] == "hold" and tc["event_id"] == 5
    assert "distribution" not in tc
    assert tc["guidance"] == (
        f"Hold for now. GW{tc['event_id']} is the best week so far (+{tc['ev_gain']:.1f} pts). "
        f"Best use: {config.CHIP_PLAN_SEASON_PRIORS['triple_captain']}."
    )


def test_outlook_guidance_hold_below_bar_with_distribution_p_beats_bar():
    gws = [5, 6, 7, 8]
    projections = _gw_projections_with_dgw(gws, dgw_gw=6)
    for g in gws:
        projections[g].loc[projections[g]["player_id"] == 13, "xpts"] = 10.0
    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    plan = build_chip_plan(squad=squad, current_gw=5, gw_projections=projections,
                           chips_played=[], horizon_gws=4,
                           player_priors=_priors_for(projections[5]))
    tc = next(o for o in plan["outlook"] if o["chip"] == "triple_captain")
    assert tc["status"] == "hold" and "distribution" in tc
    p = tc["distribution"]["p_beats_bar"] * 100
    assert tc["guidance"] == (
        f"Hold for now. GW{tc['event_id']} is the best week so far "
        f"(+{tc['ev_gain']:.1f} pts, {p:.1f}% chance to beat the {tc['bar']:.1f}-pt bar). "
        f"Best use: {config.CHIP_PLAN_SEASON_PRIORS['triple_captain']}."
    )


def test_outlook_guidance_structural_fh_cup_clash_beyond_horizon():
    gws = [5, 6, 7, 8]
    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    fx = _fixtures([(g, h, h + 10) for g in range(5, 31) for h in range(1, 11)])
    plan = build_chip_plan(
        squad=squad, current_gw=5, gw_projections=_gw_projections_with_dgw(gws, dgw_gw=None),
        chips_played=[], fixtures=fx, horizon_gws=4,
        cup_clashes={6: {"competition": "fa_cup", "label": "R5", "likely_blank": True},   # in model zone: ignored
                     15: {"competition": "fa_cup", "label": "QF", "likely_blank": True}},
    )
    fh = next(o for o in plan["outlook"] if o["chip"] == "free_hit")
    assert fh["event_id"] is None  # still no model-zone window
    assert fh["guidance"] == (
        "Hold for GW15: likely blank gameweek (FA Cup weekend), "
        "FPL confirms nearer the time."
    )


def test_outlook_and_recommendation_guidance_play_it():
    squad = _squad_15_single_team()
    market = _market_for(squad, gw_xpts=6.0)
    plan = build_chip_plan(squad, 5, {5: market}, chips_played=[])
    bb_out = next(o for o in plan["outlook"] if o["chip"] == "bench_boost")
    bb_rec = next(r for r in plan["recommendations"] if r["chip"] == "bench_boost")
    assert bb_out["status"] == "play"
    expected = (
        f"Play it in GW{bb_out['event_id']}: +{bb_out['ev_gain']:.1f} pts "
        f"over the bar of {bb_out['bar']:.1f}."
    )
    assert bb_out["guidance"] == expected
    assert bb_rec["guidance"] == expected  # outlook and recommendation agree


def test_recommendation_guidance_names_p_beats_bar_when_distribution_present():
    gws = [5, 6, 7, 8]
    projections = _gw_projections_with_dgw(gws, dgw_gw=6)
    for g in gws:
        projections[g].loc[projections[g]["player_id"] == 13, "xpts"] = 16.0
    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    plan = build_chip_plan(squad=squad, current_gw=5, gw_projections=projections,
                           chips_played=[], horizon_gws=4,
                           player_priors=_priors_for(projections[5]))
    tc = next(r for r in plan["recommendations"] if r["chip"] == "triple_captain")
    p = tc["distribution"]["p_beats_bar"] * 100
    assert tc["guidance"] == (
        f"Play it in GW{tc['event_id']}: +{tc['ev_gain']:.1f} pts over the bar of "
        f"{tc_bar(plan, 'triple_captain', tc['event_id']):.1f}. "
        f"{p:.1f}% chance it beats the bar."
    )


def test_outlook_excludes_used_chips_so_no_guidance_needed():
    """Used chips never appear in outlook at all — nothing to assert a
    guidance string on, which is the point: no guidance is emitted for them."""
    squad = _squad_15_single_team()
    market = _market_for(squad, gw_xpts=6.0)
    plan = build_chip_plan(squad, 5, {5: market},
                           chips_played=[{"name": "bboost", "event": 3}])
    assert all(o["chip"] != "bench_boost" for o in plan["outlook"])


def test_chip_guidance_never_raises_falls_back_to_generic():
    """_chip_guidance raises on a bad/missing chip key; _safe_chip_guidance
    must swallow it and fall back to a generic sentence rather than blow up
    build_chip_plan."""
    from src.chip_advisor import _safe_chip_guidance

    text = _safe_chip_guidance(
        "not_a_real_chip", status="hold", event_id=None, ev_gain=None,
        bar=0.0, distribution=None, horizon=8, transfer_plan_net_gain=0.0)
    assert text == "Hold. Best use: the right structural window for this chip."

    # a genuine chip name but a status/field combo that blows up formatting
    # (event_id required as an int for the %d-style GW interpolation)
    text2 = _safe_chip_guidance(
        "triple_captain", status="hold", event_id="not-a-number", ev_gain=None,
        bar=0.0, distribution=None, horizon=8, transfer_plan_net_gain=0.0)
    assert text2 == f"Hold. Best use: {config.CHIP_PLAN_SEASON_PRIORS['triple_captain']}."
