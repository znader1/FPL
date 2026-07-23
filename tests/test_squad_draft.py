import pandas as pd
import pytest

from src import squad_draft


def _synthetic_elements():
    """~24 players: 4 GKP, 8 DEF, 8 MID, 4 FWD across 6 teams, transformed-style."""
    rows = []
    pid = 1
    pos_plan = [("GKP", 4), ("DEF", 8), ("MID", 8), ("FWD", 4)]
    et = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
    for pos, n in pos_plan:
        for i in range(n):
            team = (pid % 6) + 1
            # first of each position is a cheap high-ppg small-sample "mirage"
            mirage = (i == 0 and pos in ("GKP", "FWD"))
            rows.append({
                "id": pid, "web_name": f"{pos}{i}", "team": team,
                "team_short": f"T{team}", "team_name": f"Team {team}",
                "element_type": et[pos], "pos": pos,
                "now_cost": 40 + (i * 5), "price_m": (40 + i * 5) / 10.0,
                "status": "a", "chance_of_playing_next_round": None,
                "points_per_game": 8.0 if mirage else float(2 + i),
                "form": "0.0", "ep_next": "0.0",
                "minutes": 90 if mirage else (1500 + i * 200),
                "starts": 1 if mirage else (18 + i),
                "selected_by_percent": "5.0", "penalties_order": None,
                "expected_goals_per_90": 0.2, "expected_assists_per_90": 0.1,
                "expected_goal_involvements_per_90": 0.3,
                "expected_goals_conceded_per_90": 1.0, "saves_per_90": 1.5,
            })
            pid += 1
    return pd.DataFrame(rows)


def _synthetic_fixtures(n_gws=5, n_teams=6):
    rows = []
    for gw in range(1, n_gws + 1):
        for h in range(1, n_teams, 2):
            rows.append({"event": gw, "team_h": h, "team_a": h + 1,
                         "finished": False, "team_h_difficulty": 3, "team_a_difficulty": 3})
    return pd.DataFrame(rows)


def _teams_short(n_teams=6):
    return {t: f"T{t}" for t in range(1, n_teams + 1)}


def test_build_squad_returns_legal_15_within_budget():
    els = _synthetic_elements()
    fx = _synthetic_fixtures()
    res = squad_draft.build_squad_from_frames(
        els, fx, _teams_short(),
        {"gw_start": 1, "horizon_gws": 5, "budget_m": 100.0, "projection_basis": "ppg"},
    )
    assert res["ok"] is True, res.get("reason")
    squad = pd.DataFrame(res["squad"])
    assert len(squad) == 15
    counts = squad["pos"].value_counts().to_dict()
    assert counts == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert res["squad_cost_m"] <= 100.0 + 1e-6
    assert (squad["team_short"].value_counts() <= 3).all()
