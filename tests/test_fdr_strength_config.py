import pandas as pd

from src import config, projections
from src.config_overrides import config_overrides


def _inputs():
    elements = pd.DataFrame({
        "id": [1, 2],
        "web_name": ["Tough", "Even"],
        "team": [1, 3],
        "element_type": [3, 3],
        "now_cost": [80, 80],
        "points_per_game": [5.0, 5.0],
        "form": [5.0, 5.0],
        "minutes": [900, 900],
        "chance_of_playing_next_round": [100, 100],
        "status": ["a", "a"],
        "total_points": [50, 50],
    })
    # Team 1 away at team 2, difficulty 5; team 3 home to team 4, difficulty 3.
    fixtures = pd.DataFrame([(5, 2, 1, 2, 5), (5, 3, 4, 3, 3)],
                            columns=["event", "team_h", "team_a",
                                     "team_h_difficulty", "team_a_difficulty"])
    return elements, fixtures, {1: "AAA", 2: "BBB", 3: "CCC", 4: "DDD"}


def _xpts(**kwargs):
    elements, fixtures, short = _inputs()
    proj = projections.project_elements_next_gws(
        elements=elements, fixtures=fixtures, teams_short_map=short,
        gw_start=5, horizon_gws=1, **kwargs)
    out = proj.set_index("id")["xpts_gw5"]
    return float(out[1]), float(out[2])


BASE = {"PROJ_DIFFICULTY_SOURCE": "fpl", "PROJ_MODEL_BLEND_WEIGHT": 0.0}


def test_config_strength_one_matches_explicit_one():
    with config_overrides({**BASE, "PROJ_FDR_STRENGTH": 1.0}):
        from_config = _xpts()
        explicit = _xpts(fdr_strength=1.0)
    assert from_config == explicit


def test_config_strength_amplifies_tough_fixture_only():
    with config_overrides({**BASE, "PROJ_FDR_STRENGTH": 1.0}):
        tough_1, even_1 = _xpts()
    with config_overrides({**BASE, "PROJ_FDR_STRENGTH": 2.0}):
        tough_2, even_2 = _xpts()
    assert tough_2 < tough_1
    assert abs(even_2 - even_1) < 1e-9


def test_explicit_argument_still_wins():
    with config_overrides({**BASE, "PROJ_FDR_STRENGTH": 2.0}):
        assert _xpts(fdr_strength=1.0) != _xpts()
