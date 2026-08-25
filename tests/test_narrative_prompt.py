from src import league_strategy


def test_user_message_includes_diff_ev_and_captain_differential():
    analysis = {
        "league": {"name": "L"}, "user": {"player_name": "Me", "rank": 3, "total": 100},
        "rivals_above": [], "rivals_below": [],
    }
    candidates = [{
        "id": 1, "web_name": "A", "team_short": "AAA", "model_xpts_horizon": 12.0,
        "model_xpts_per_gw": {"gw1": 4.0}, "fixtures": {"gw1": "BBB/h"},
        "league_ownership": 0.06, "differential_ev": 5.4,
    }]
    cap = {"reason": "Cap faces a hard run; A is a 6%-owned differential (+5.4 diff-EV)."}
    msg = league_strategy.build_user_message(analysis, "differential", candidates,
                                             fixture_ticker=None, captain_differential=cap)
    assert "diff_ev=5.4" in msg
    assert "league_own=0.06" in msg
    assert "Cap faces a hard run" in msg
