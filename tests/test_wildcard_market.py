import pandas as pd

from src import config, optimizer, projections


def _inputs():
    elements = pd.DataFrame({
        "id": [1, 2],
        "web_name": ["Recent", "SeasonOnly"],
        "team": [1, 2],
        "element_type": [3, 3],
        "now_cost": [80, 60],
        "points_per_game": [4.0, 3.0],
        "form": [4.0, 3.0],
        "minutes": [900, 400],
        "starts": [10, 4],
        "chance_of_playing_next_round": [100, 100],
        "status": ["a", "a"],
        "total_points": [40, 20],
    })
    # five finished rounds (events 1..5) for both teams, planning GW 6
    fixtures = pd.DataFrame(
        [(e, 1, 2, 3, 3) for e in range(1, 6)] + [(6, 2, 1, 3, 3)],
        columns=["event", "team_h", "team_a", "team_h_difficulty", "team_a_difficulty"],
    )
    return elements, fixtures, {1: "AAA", 2: "BBB"}


def test_start_share_prefers_recent_window_then_season(monkeypatch):
    monkeypatch.setattr(config, "PROJ_DIFFICULTY_SOURCE", "fpl", raising=False)
    recent = pd.DataFrame({
        "player_id": [1],
        "recent_gw_avg_points": [4.0],
        "recent_gw_avg_fixture_count": [1.0],
        "recent_gw_samples": [3],
        "recent_gw_last": [5],
        "recent_gw_avg_minutes": [80.0],
        "recent_gw_avg_starts": [0.6],
        "recent_history_window_gws": [5],
        "recent_history_max_gw": [5],
    })
    monkeypatch.setattr(projections, "player_recent_gw_map", lambda **kw: recent)
    elements, fixtures, short = _inputs()
    proj = projections.project_elements_next_gws(
        elements=elements, fixtures=fixtures, teams_short_map=short, gw_start=6, horizon_gws=1
    ).set_index("id")
    assert abs(float(proj.loc[1, "start_share"]) - 0.6) < 1e-9   # recent window wins
    assert abs(float(proj.loc[2, "start_share"]) - 0.8) < 1e-9   # 4 starts / 5 played


def test_team_defence_table_ranks_lower_xga_first():
    ratings = {
        "_league": 1.3,
        1: {"attack": 1.0, "defense": 1.2, "samples": 9.0},
        2: {"attack": 1.0, "defense": 0.8, "samples": 5.0},
        3: {"attack": 1.0, "defense": 1.0, "samples": 7.0},
    }
    table = projections.team_defence_table(ratings).set_index("team")
    assert table.loc[2, "team_def_rank"] == 1
    assert table.loc[3, "team_def_rank"] == 2
    assert table.loc[1, "team_def_rank"] == 3
    assert table.loc[2, "team_rated_matches"] == 5.0


def test_team_defence_table_empty_when_no_ratings():
    assert projections.team_defence_table(None).empty


def test_prepare_chip_market_keeps_optional_columns():
    df = pd.DataFrame({
        "id": [1, 2], "web_name": ["a", "b"], "pos": ["DEF", "MID"], "team": [1, 2],
        "price_m": [4.5, 5.0], "wildcard_score": [3.0, 4.0], "status": ["a", "a"],
        "start_share": [0.9, 0.5], "p_dc": [0.6, 0.2], "p_clean_sheet": [0.3, 0.0],
        "injury_flag": [False, True], "team_def_rank": [2, 9], "team_rated_matches": [8.0, 8.0],
        "ep_goals": [0.1, 0.5], "ep_assists": [0.1, 0.4], "ep_dc": [1.0, 0.2], "ep_saves": [0.0, 0.0],
        "selected_by_percent": [5.0, 40.0],
    })
    market = optimizer._prepare_chip_market(df, score_col="wildcard_score", shape={"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3})
    for col in ["start_share", "p_dc", "p_clean_sheet", "injury_flag", "team_def_rank",
                "team_rated_matches", "ep_goals", "ep_assists", "ep_dc", "ep_saves", "selected_by_percent"]:
        assert col in market.columns, col
