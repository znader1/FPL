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


def test_minutes_shrink_kills_small_sample_mirage():
    els = _synthetic_elements()
    # GKP0 is the mirage: 8.0 ppg over 90 mins. After shrink it must fall far.
    shrunk = squad_draft._apply_minutes_shrink(els, 500.0)
    mirage = shrunk[shrunk["web_name"] == "GKP0"].iloc[0]
    assert mirage["points_per_game"] < 2.0            # 8.0 * 90/(90+500) ~= 1.22
    nailed = shrunk[shrunk["web_name"] == "GKP3"].iloc[0]
    assert nailed["points_per_game"] > 0.7 * nailed["raw_ppg"]  # 2100 mins barely moves


def test_flagged_players_excluded_unless_included():
    els = _synthetic_elements()
    els.loc[els["web_name"] == "MID7", "status"] = "i"
    fx, ts = _synthetic_fixtures(), _teams_short()
    res = squad_draft.build_squad_from_frames(
        els, fx, ts, {"gw_start": 1, "include_flagged": False})
    ids = {int(r["player_id"]) for r in res["squad"]}
    mid7_id = int(els[els["web_name"] == "MID7"].iloc[0]["id"])
    assert mid7_id not in ids


def test_determinism_same_inputs_same_squad():
    els, fx, ts = _synthetic_elements(), _synthetic_fixtures(), _teams_short()
    params = {"gw_start": 1, "horizon_gws": 5}
    a = squad_draft.build_squad_from_frames(els, fx, ts, params)
    b = squad_draft.build_squad_from_frames(els, fx, ts, params)
    assert [r["player_id"] for r in a["squad"]] == [r["player_id"] for r in b["squad"]]
