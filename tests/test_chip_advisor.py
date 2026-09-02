import pandas as pd

from src.chip_advisor import chip_windows, team_fixture_counts


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
    # bench_boost base threshold is 5.0; GW5 vs expiry GW19 is outside the ramp
    assert effective_min_ev("bench_boost", target_gw=5, expires_gw=19) == 5.0


def test_effective_min_ev_decays_inside_ramp():
    # ramp is 5 GWs: at 2 GWs left the threshold is base * 2/5
    v = effective_min_ev("bench_boost", target_gw=17, expires_gw=19)
    assert abs(v - 5.0 * 2 / 5) < 1e-9


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
