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


def test_annotate_horizon_plan_moves():
    # A picked runner-up's pitch card is drawn from the plan's own move dicts,
    # which are separate from preview["moves"] — they need the label too.
    elements = pd.DataFrame([{"id": 10, "team": 1}, {"id": 20, "team": 3}])
    mv = lambda: {"sell": {"id": 10}, "buy": {"id": 20}}  # noqa: E731
    plan = {"verdict_detail": {
        "moves": [mv()], "runner_ups": [mv()], "roll_alternative": {"moves": [mv()]},
    }}
    annotate_moves_next_fixture({"moves": []}, elements, _fixtures(), TEAMS, 2, plan=plan)
    d = plan["verdict_detail"]
    for move in (d["moves"][0], d["runner_ups"][0], d["roll_alternative"]["moves"][0]):
        assert move["buy"]["next_fixture"] == "ARS (A)"
        assert move["sell"]["next_fixture"] == "BOU (H)"
    # A roll verdict with no alternative must not break.
    annotate_moves_next_fixture({}, elements, _fixtures(), TEAMS, 2,
                                plan={"verdict_detail": {"roll_alternative": None}})
