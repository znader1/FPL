import pandas as pd

from src import projections
from src.projections import (
    DIFFICULTY_MULTIPLIER,
    difficulty_multiplier,
    difficulty_multiplier_smooth,
    xg_team_difficulty_for_gw,
)


def test_smooth_matches_discrete_at_integer_anchors():
    for d in (1, 2, 3, 4, 5):
        assert abs(difficulty_multiplier_smooth(d) - DIFFICULTY_MULTIPLIER[d]) < 1e-9
        assert abs(difficulty_multiplier_smooth(d) - difficulty_multiplier(d)) < 1e-9


def test_smooth_interpolates_between_anchors():
    m25 = difficulty_multiplier_smooth(2.5)
    lo, hi = DIFFICULTY_MULTIPLIER[2], DIFFICULTY_MULTIPLIER[3]
    assert abs(m25 - (lo + hi) / 2.0) < 1e-9
    # Strictly between the two anchors, unlike the rounding version.
    assert min(lo, hi) < m25 < max(lo, hi)


def test_smooth_clamps_and_handles_bad_input():
    assert difficulty_multiplier_smooth(0.0) == DIFFICULTY_MULTIPLIER[1]
    assert difficulty_multiplier_smooth(9.9) == DIFFICULTY_MULTIPLIER[5]
    assert difficulty_multiplier_smooth(float("nan")) == 1.0
    assert difficulty_multiplier_smooth("junk") == 1.0


def test_xg_team_difficulty_for_gw_averages_dgw():
    ratings = {
        "_league": 1.4,
        1: {"attack": 1.2, "defense": 0.9},
        2: {"attack": 0.9, "defense": 1.3},
        3: {"attack": 1.0, "defense": 1.0},
    }
    fixtures = pd.DataFrame(
        [
            (5, 1, 2),  # team 1 home vs 2
            (5, 3, 1),  # team 1 away at 3 — DGW for team 1
        ],
        columns=["event", "team_h", "team_a"],
    )
    out = xg_team_difficulty_for_gw(ratings, fixtures, 5)
    assert set(out) == {1, 2, 3}
    for v in out.values():
        assert 1.0 <= v <= 5.0
    # Team 1 faces leaky team 2 at home and average team 3 away: its avg
    # difficulty must be easier (lower) than team 2's, who face 1's tight
    # defence away.
    assert out[1] < out[2]


def test_default_source_leaves_projection_path_unchanged(monkeypatch):
    # With PROJ_DIFFICULTY_SOURCE="fpl" (default) the ratings resolver must
    # never even be consulted.
    from src import config

    monkeypatch.setattr(config, "PROJ_DIFFICULTY_SOURCE", "fpl", raising=False)
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("resolver must not run for source=fpl")

    monkeypatch.setattr(projections, "resolve_projection_difficulty_ratings", boom)

    elements = pd.DataFrame({
        "id": [1], "web_name": ["P1"], "team": [1], "element_type": [3],
        "now_cost": [50], "points_per_game": [4.0], "form": [4.0],
        "minutes": [900], "chance_of_playing_next_round": [100],
        "status": ["a"], "total_points": [40],
    })
    fixtures = pd.DataFrame([(5, 1, 2, 3, 3)],
                            columns=["event", "team_h", "team_a",
                                     "team_h_difficulty", "team_a_difficulty"])
    proj = projections.project_elements_next_gws(
        elements=elements, fixtures=fixtures, teams_short_map={1: "AAA", 2: "BBB"},
        gw_start=5, horizon_gws=1,
    )
    assert called["n"] == 0
    assert "xpts_gw5" in proj.columns


def test_badge_label_follows_difficulty_override():
    from src import transforms

    elements = pd.DataFrame({"id": [1], "team": [1], "now_cost": [50]})
    fixtures = pd.DataFrame([(5, 1, 2, 2, 3)],
                            columns=["event", "team_h", "team_a",
                                     "team_h_difficulty", "team_a_difficulty"])
    short = {1: "AAA", 2: "BBB"}
    base = transforms.annotate_elements_with_gw_fixtures(elements, fixtures, 5, short)
    assert "(D2)" in base["gw_fixtures"].iloc[0]  # FPL FDR says 2

    over = transforms.annotate_elements_with_gw_fixtures(
        elements, fixtures, 5, short, diff_by_team={1: 3.6})
    assert "(D4)" in over["gw_fixtures"].iloc[0]  # override rounds to 4
    assert abs(float(over["gw_diff_avg"].iloc[0]) - 3.6) < 1e-9  # continuous kept


def test_market_difficulty_blends_first_gw_only(monkeypatch):
    from src import config

    monkeypatch.setattr(config, "PROJ_DIFFICULTY_SOURCE", "xg_ratings", raising=False)
    monkeypatch.setattr(config, "ODDS_DIFFICULTY_BLEND_WEIGHT", 0.5, raising=False)
    # xG ratings say difficulty 3.0 for team 1 in both GWs
    monkeypatch.setattr(projections, "resolve_projection_difficulty_ratings",
                        lambda tsm: {"_league": 1.4, 1: {"attack": 1.0, "defense": 1.0},
                                     2: {"attack": 1.0, "defense": 1.0}})
    monkeypatch.setattr(projections, "xg_team_difficulty_for_gw",
                        lambda ratings, fixtures, gw: {1: 3.0, 2: 3.0})
    # Market says team 1's next fixture is much easier (1.0)
    monkeypatch.setattr(projections, "resolve_market_difficulty",
                        lambda names: {1: 1.0})

    elements = pd.DataFrame({
        "id": [1], "web_name": ["P1"], "team": [1], "team_name": ["Alpha"],
        "element_type": [3], "now_cost": [50], "points_per_game": [4.0],
        "form": [4.0], "minutes": [900], "chance_of_playing_next_round": [100],
        "status": ["a"], "total_points": [40],
    })
    fixtures = pd.DataFrame([(5, 1, 2, 3, 3), (6, 2, 1, 3, 3)],
                            columns=["event", "team_h", "team_a",
                                     "team_h_difficulty", "team_a_difficulty"])
    proj = projections.project_elements_next_gws(
        elements=elements, fixtures=fixtures, teams_short_map={1: "AAA", 2: "BBB"},
        gw_start=5, horizon_gws=2)
    r = proj.iloc[0]
    assert abs(float(r["diff_avg_gw5"]) - 2.0) < 1e-9   # 0.5*1.0 + 0.5*3.0
    assert abs(float(r["diff_avg_gw6"]) - 3.0) < 1e-9   # market never touches later GWs


def test_no_market_data_leaves_difficulty_unchanged(monkeypatch):
    from src import config

    monkeypatch.setattr(config, "PROJ_DIFFICULTY_SOURCE", "xg_ratings", raising=False)
    monkeypatch.setattr(projections, "resolve_projection_difficulty_ratings",
                        lambda tsm: {"_league": 1.4, 1: {"attack": 1.0, "defense": 1.0},
                                     2: {"attack": 1.0, "defense": 1.0}})
    monkeypatch.setattr(projections, "xg_team_difficulty_for_gw",
                        lambda ratings, fixtures, gw: {1: 3.0, 2: 3.0})
    monkeypatch.setattr(projections, "resolve_market_difficulty", lambda names: {})

    elements = pd.DataFrame({
        "id": [1], "web_name": ["P1"], "team": [1], "team_name": ["Alpha"],
        "element_type": [3], "now_cost": [50], "points_per_game": [4.0],
        "form": [4.0], "minutes": [900], "chance_of_playing_next_round": [100],
        "status": ["a"], "total_points": [40],
    })
    fixtures = pd.DataFrame([(5, 1, 2, 3, 3)],
                            columns=["event", "team_h", "team_a",
                                     "team_h_difficulty", "team_a_difficulty"])
    proj = projections.project_elements_next_gws(
        elements=elements, fixtures=fixtures, teams_short_map={1: "AAA", 2: "BBB"},
        gw_start=5, horizon_gws=1)
    assert abs(float(proj.iloc[0]["diff_avg_gw5"]) - 3.0) < 1e-9
