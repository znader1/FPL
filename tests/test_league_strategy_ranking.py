from src import config, league_strategy


def _analysis(ownership):
    return {
        "differentials": {"owned_by_me_not_rivals": [], "owned_by_rivals_not_me": [], "shared": []},
        "league_ownership": ownership,
        "rivals_above": [], "rivals_below": [],
        "rival_squads": {}, "my_squad": {"picks": []},
    }


def _meta(pid, name, xpts, own_pct, pos=3):
    return {"id": pid, "web_name": name, "position_id": pos,
            "model_xpts_horizon": xpts, "ep_next": xpts, "selected_by_percent": own_pct,
            "now_cost": 70, "team_short": "XYZ"}


def test_differential_mode_ev_ranking_beats_raw_xpts(monkeypatch):
    monkeypatch.setattr(config, "LEAGUE_EV_RANKING", True, raising=False)
    # A: 12 xPts, 0% league-owned. B: 13 xPts but 15% league-owned (rivals already have B).
    # C: cheap filler MID, 90% GLOBALLY owned -> drags the position template DOWN so both A and
    #    B sit above it; C is filtered out of differential mode (league_own 0.40 >= 0.20).
    # template(MID) = (3*12 + 3*13 + 90*3)/96 = 345/96 = 3.59375
    #   A EV = (12 - 3.59375) * (1 - 0.00) = 8.406
    #   B EV = (13 - 3.59375) * (1 - 0.15) = 7.995   -> A ranks first despite lower raw xPts.
    elements = {
        1: _meta(1, "A", 12.0, "3.0"),
        2: _meta(2, "B", 13.0, "3.0"),
        3: _meta(3, "C", 3.0, "90.0"),
    }
    templates = league_strategy.ownership_ev.compute_position_templates(elements)
    analysis = _analysis({1: 0.0, 2: 0.15, 3: 0.40})
    out = league_strategy._candidate_targets(analysis, elements, "differential", templates)
    assert out[0]["web_name"] == "A"
    assert "differential_ev" in out[0]


def test_flag_off_uses_legacy_raw_xpts_order(monkeypatch):
    monkeypatch.setattr(config, "LEAGUE_EV_RANKING", False, raising=False)
    elements = {1: _meta(1, "A", 12.0, "3.0"), 2: _meta(2, "B", 13.0, "60.0")}
    templates = league_strategy.ownership_ev.compute_position_templates(elements)
    analysis = _analysis({1: 0.0, 2: 0.0})
    out = league_strategy._candidate_targets(analysis, elements, "differential", templates)
    # Legacy sort is by raw xPts -> B (13) first.
    assert out[0]["web_name"] == "B"
