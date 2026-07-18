from src import league_strategy


def _meta(pid, name, xpts, own_pct, cost, team, pos=4):
    return {"id": pid, "web_name": name, "position_id": pos, "model_xpts_horizon": xpts,
            "ep_next": xpts, "selected_by_percent": own_pct, "now_cost": cost, "team_short": team}


def _ticker(bands):  # bands: {team_short: band}
    return {"teams": [{"team_short": t, "avg_difficulty": 3.5, "band": b} for t, b in bands.items()]}


def _analysis(ownership):
    return {"league_ownership": ownership}


def test_flag_emitted_on_hard_fixture_with_alt():
    # Cap = premium (cost 130) MID/FWD, 80% league-owned, team AAA has a hard run.
    # Alt = 5% owned, high xPts differential on team BBB.
    elements = {
        1: _meta(1, "Cap", 9.0, "55.0", 130, "AAA"),
        2: _meta(2, "Alt", 8.0, "6.0", 95, "BBB"),
        3: _meta(3, "Filler", 4.0, "40.0", 70, "CCC"),
    }
    templates = league_strategy.ownership_ev.compute_position_templates(elements)
    analysis = _analysis({1: 0.80, 2: 0.05, 3: 0.40})
    ticker = _ticker({"AAA": "hard", "BBB": "easy"})
    flag = league_strategy.detect_captain_differential(analysis, elements, templates, ticker)
    assert flag is not None
    assert flag["consensus_captain"]["web_name"] == "Cap"
    assert flag["alternative"]["web_name"] == "Alt"


def test_no_flag_when_fixture_easy():
    elements = {1: _meta(1, "Cap", 9.0, "55.0", 130, "AAA"),
                2: _meta(2, "Alt", 8.0, "6.0", 95, "BBB")}
    templates = league_strategy.ownership_ev.compute_position_templates(elements)
    analysis = _analysis({1: 0.80, 2: 0.05})
    ticker = _ticker({"AAA": "easy", "BBB": "easy"})
    assert league_strategy.detect_captain_differential(analysis, elements, templates, ticker) is None


def test_no_flag_when_no_low_owned_alt():
    elements = {1: _meta(1, "Cap", 9.0, "55.0", 130, "AAA"),
                2: _meta(2, "Alt", 8.0, "50.0", 95, "BBB")}  # alt is 50% owned -> not a differential
    templates = league_strategy.ownership_ev.compute_position_templates(elements)
    analysis = _analysis({1: 0.80, 2: 0.50})
    ticker = _ticker({"AAA": "hard", "BBB": "easy"})
    assert league_strategy.detect_captain_differential(analysis, elements, templates, ticker) is None
