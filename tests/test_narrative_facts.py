import pandas as pd

from src import narrative_facts


def _fixtures():
    # fixture id, home, away
    return pd.DataFrame([
        (101, 1, 2), (102, 2, 1), (103, 1, 3), (104, 3, 1), (105, 1, 2), (106, 1, 4),
    ], columns=["id", "team_h", "team_a"])


def _matches():
    rows = []
    # player 10 (team 1): 3 meetings vs team 2 (fixtures 101, 102, 105), 2 vs team 3, 1 vs team 4
    pts = {101: 8, 102: 2, 105: 12, 103: 6, 104: 1, 106: 7}
    goals = {101: 1, 102: 0, 105: 2, 103: 1, 104: 0, 106: 1}
    for ev, fid in enumerate([101, 102, 103, 104, 105, 106], start=1):
        rows.append({"element": 10, "element_type": 4, "team_id": 1, "fixture": fid, "event": ev,
                     "minutes": 90, "total_points": pts[fid], "goals_scored": goals[fid], "assists": 0})
    return pd.DataFrame(rows)


def _elements():
    return pd.DataFrame({"id": [10, 11], "goals_scored": [48, 3], "assists": [12, 1], "clean_sheets": [0, 5]})


def test_vs_opponent_none_when_no_meetings():
    facts = narrative_facts.for_players([11], {11: 2}, _matches(), _fixtures(), _elements())
    assert facts[11]["vs_opponent"] is None


def test_vs_opponent_aggregates_last_meetings():
    facts = narrative_facts.for_players([10], {10: 2}, _matches(), _fixtures(), _elements())
    vs = facts[10]["vs_opponent"]
    assert vs == {"games": 3, "goals": 3, "assists": 0, "points": 22}


def test_milestone_within_five_of_fifty():
    facts = narrative_facts.for_players([10, 11], {}, _matches(), _fixtures(), _elements())
    assert facts[10]["milestone"] == {"stat": "goals", "current": 48, "target": 50}
    assert facts[11]["milestone"] is None


def test_streak_counts_consecutive_returns():
    # last matches by event: 106 (7), 105 (12), 104 (1) → streak of 2
    facts = narrative_facts.for_players([10], {}, _matches(), _fixtures(), _elements())
    assert facts[10]["streak"] == 2


def test_missing_history_gives_empty_facts():
    facts = narrative_facts.for_players([10], {10: 2}, pd.DataFrame(), pd.DataFrame(), _elements())
    assert facts[10] == {"vs_opponent": None, "milestone": {"stat": "goals", "current": 48, "target": 50}, "streak": 0}
