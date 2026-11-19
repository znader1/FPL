import pandas as pd

from api.main import annotate_moves_next_fixture, next_fixture_labels_by_team

TEAMS = {1: "ARS", 2: "AVL", 3: "BOU"}


def _fixtures():
    return pd.DataFrame([
        {"event": 2, "team_h": 1, "team_a": 3},   # ARS vs BOU
        {"event": 3, "team_h": 2, "team_a": 1},   # other GW — ignored
    ])


def test_labels_by_team_home_away_and_blank():
    labels = next_fixture_labels_by_team(_fixtures(), TEAMS, 2)
    assert labels[1] == "BOU (H)"
    assert labels[3] == "ARS (A)"
    assert 2 not in labels  # AVL blank in GW2


def test_annotate_moves_and_hot_targets():
    elements = pd.DataFrame([
        {"id": 10, "team": 1},
        {"id": 20, "team": 3},
        {"id": 30, "team": 2},  # blank-GW team
    ])
    preview = {
        "moves": [{
            "sell": {"id": 10, "name": "A"},
            "buy": {"id": 20, "name": "B"},
        }],
        "hot_by_position": {"MID": [{"id": 30, "name": "C"}, {"id": 20, "name": "B"}]},
    }
    annotate_moves_next_fixture(preview, elements, _fixtures(), TEAMS, 2)
    assert preview["moves"][0]["sell"]["next_fixture"] == "BOU (H)"
    assert preview["moves"][0]["buy"]["next_fixture"] == "ARS (A)"
    assert "next_fixture" not in preview["hot_by_position"]["MID"][0]  # blank GW
    assert preview["hot_by_position"]["MID"][1]["next_fixture"] == "ARS (A)"


def test_annotate_never_raises_on_empty():
    annotate_moves_next_fixture({}, pd.DataFrame(), pd.DataFrame(), TEAMS, 2)
    annotate_moves_next_fixture({"moves": None}, None, None, TEAMS, 2)


def test_annotate_verdict_moves_runner_ups_and_moves():
    from api.main import annotate_verdict_moves
    proj = pd.DataFrame([
        {"id": 10, "fixtures_gw2": "H-BOU(D2)", "xpts_gw2": 1.78},
        {"id": 20, "fixtures_gw2": "A-ARS(D4)", "xpts_gw2": 5.876},
        {"id": 30, "fixtures_gw2": "", "xpts_gw2": 0.0},
    ])
    plan = {"verdict_detail": {
        "moves": [{"sell": {"id": 10}, "buy": {"id": 20}}],
        "runner_ups": [{"sell": {"id": 10}, "buy": {"id": 30}}],
        "roll_alternative": None,
    }}
    annotate_verdict_moves(plan, proj, 2, {1: "BOU (H)", 3: "ARS (A)"}, {10: 1, 20: 3, 30: 2})
    buy = plan["verdict_detail"]["moves"][0]["buy"]
    assert buy["next_fixtures"] == "A-ARS(D4)" and buy["xpts"] == 5.88 and buy["next_fixture"] == "ARS (A)"
    sell = plan["verdict_detail"]["moves"][0]["sell"]
    assert sell["next_fixtures"] == "H-BOU(D2)" and sell["xpts"] == 1.78
    blank = plan["verdict_detail"]["runner_ups"][0]["buy"]
    assert "next_fixtures" not in blank and "next_fixture" not in blank and blank["xpts"] == 0.0


def test_annotate_verdict_moves_roll_alternative():
    from api.main import annotate_verdict_moves
    proj = pd.DataFrame([{"id": 20, "fixtures_gw2": "A-ARS(D4)", "xpts_gw2": 3.0}])
    plan = {"verdict_detail": {"moves": [], "runner_ups": [],
                               "roll_alternative": {"moves": [{"sell": {"id": 99}, "buy": {"id": 20}}]}}}
    annotate_verdict_moves(plan, proj, 2, {}, {})
    buy = plan["verdict_detail"]["roll_alternative"]["moves"][0]["buy"]
    assert buy["next_fixtures"] == "A-ARS(D4)" and buy["xpts"] == 3.0
    assert "xpts" not in plan["verdict_detail"]["roll_alternative"]["moves"][0]["sell"]  # unknown id


def test_annotate_verdict_moves_tolerates_missing_plan():
    from api.main import annotate_verdict_moves
    annotate_verdict_moves(None, pd.DataFrame(), 2, {}, {})
    annotate_verdict_moves({"verdict_detail": None}, pd.DataFrame(), 2, {}, {})
