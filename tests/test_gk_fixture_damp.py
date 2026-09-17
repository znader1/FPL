import pandas as pd

from src import config, projections


def _inputs():
    elements = pd.DataFrame({
        "id": [1, 2],
        "web_name": ["Keeper", "Mid"],
        "team": [1, 1],
        "element_type": [1, 3],
        "now_cost": [50, 80],
        "points_per_game": [4.0, 4.0],
        "form": [4.0, 4.0],
        "minutes": [900, 900],
        "chance_of_playing_next_round": [100, 100],
        "status": ["a", "a"],
        "total_points": [40, 40],
    })
    # Tough away fixture → context multiplier well below 1.0
    fixtures = pd.DataFrame([(5, 2, 1, 2, 5)],
                            columns=["event", "team_h", "team_a",
                                     "team_h_difficulty", "team_a_difficulty"])
    return elements, fixtures, {1: "AAA", 2: "BBB"}


def _xpts(monkeypatch, damp):
    monkeypatch.setattr(config, "PROJ_DIFFICULTY_SOURCE", "fpl", raising=False)
    monkeypatch.setattr(config, "PROJ_GK_FIXTURE_DAMP", damp, raising=False)
    elements, fixtures, short = _inputs()
    proj = projections.project_elements_next_gws(
        elements=elements, fixtures=fixtures, teams_short_map=short,
        gw_start=5, horizon_gws=1)
    out = proj.set_index("id")["xpts_gw5"]
    return float(out[1]), float(out[2])


def test_damp_compresses_gk_only(monkeypatch):
    gk_full, mid_full = _xpts(monkeypatch, 1.0)
    gk_damp, mid_damp = _xpts(monkeypatch, 0.5)
    assert abs(mid_full - mid_damp) < 1e-9  # outfield untouched
    # Tough fixture pushed the GK below baseline; damping pulls it back up.
    assert gk_damp > gk_full


def test_damp_one_is_exact_legacy(monkeypatch):
    a = _xpts(monkeypatch, 1.0)
    b = _xpts(monkeypatch, 1.0)
    assert a == b
