"""GW1 projection with FPL's ep_next present.

FPL's ep_next already bakes in fixture count, difficulty, venue and form, so
only the baseline share of the first-GW blend may be scaled by the fixture
context, and a blank GW is zero for everyone.
"""
import pandas as pd
import pytest

from src import config, projections


def _elements(ep_next):
    return pd.DataFrame({
        "id": [1],
        "web_name": ["Mid"],
        "team": [1],
        "element_type": [3],
        "now_cost": [80],
        "points_per_game": [4.0],
        "form": [4.0],
        "minutes": [900],
        "chance_of_playing_next_round": [100],
        "status": ["a"],
        "total_points": [40],
        "ep_next": [ep_next],
    })


def _history():
    rows = []
    for gw in range(1, 5):
        rows.append({"player_id": 1, "gw": gw, "gw_total_points": 6.0, "gw_minutes": 90,
                     "gw_starts": 1, "gw_fixture_count": 1, "gw_team_id_end": 1,
                     "gw_team_difficulty_avg": 3.0})
    return pd.DataFrame(rows)


@pytest.fixture
def baseline_only(monkeypatch):
    monkeypatch.setattr(config, "PROJ_DIFFICULTY_SOURCE", "fpl", raising=False)
    monkeypatch.setattr(config, "PROJ_MODEL_BLEND_WEIGHT", 0.0, raising=False)
    monkeypatch.setattr(config, "PROJ_APPLY_MINUTES_MODEL", False, raising=False)
    monkeypatch.setattr(config, "PROJ_EP_NEXT_BLEND_WEIGHT", 0.5, raising=False)
    monkeypatch.setattr(projections, "load_latest_player_gw_history", lambda **kw: _history())


def _project(fixtures, ep_next=5.0):
    proj = projections.project_elements_next_gws(
        elements=_elements(ep_next), fixtures=fixtures, teams_short_map={1: "AAA", 2: "BBB"},
        gw_start=5, horizon_gws=1)
    return proj.set_index("id").loc[1]


def _ctx(row):
    return (projections.difficulty_multiplier(float(row["diff_avg_gw5"]))
            * float(row["home_away_mult_gw5"]) * float(row["opp_form_mult_gw5"])
            * float(row["team_form_mult_gw5"]))


def test_blank_gw_is_zero_even_with_ep_next(baseline_only):
    fixtures = pd.DataFrame([(6, 2, 1, 2, 5)],
                            columns=["event", "team_h", "team_a", "team_h_difficulty", "team_a_difficulty"])
    row = _project(fixtures, ep_next=0.0)
    assert float(row["xpts_gw5"]) == 0.0


def test_ep_next_share_is_not_scaled_by_fixture_context(baseline_only):
    fixtures = pd.DataFrame([(5, 2, 1, 2, 5)],
                            columns=["event", "team_h", "team_a", "team_h_difficulty", "team_a_difficulty"])
    row = _project(fixtures, ep_next=5.0)
    ctx = _ctx(row)
    assert ctx < 0.95  # tough away fixture really moves the baseline share
    assert row["recent_history_available"]
    expected = 0.5 * 5.0 + 0.5 * float(row["baseline_blended_xpts"]) * ctx
    assert float(row["xpts_gw5"]) == pytest.approx(expected, abs=1e-3)


def test_ep_next_without_history_is_taken_raw(baseline_only, monkeypatch):
    monkeypatch.setattr(projections, "load_latest_player_gw_history", lambda **kw: pd.DataFrame())
    fixtures = pd.DataFrame([(5, 2, 1, 2, 5)],
                            columns=["event", "team_h", "team_a", "team_h_difficulty", "team_a_difficulty"])
    row = _project(fixtures, ep_next=5.0)
    assert not row["recent_history_available"]
    assert float(row["xpts_gw5"]) == pytest.approx(5.0, abs=1e-6)


def test_double_gw_scales_only_the_baseline_share(baseline_only):
    fixtures = pd.DataFrame([(5, 2, 1, 2, 5), (5, 1, 2, 3, 3)],
                            columns=["event", "team_h", "team_a", "team_h_difficulty", "team_a_difficulty"])
    row = _project(fixtures, ep_next=8.0)
    assert int(row["fixture_count_gw5"]) == 2
    eff = 1.0 + float(config.PROJ_DGW_EXTRA_FIXTURE_DISCOUNT)
    expected = 0.5 * 8.0 + 0.5 * float(row["baseline_blended_xpts"]) * eff * _ctx(row)
    assert float(row["xpts_gw5"]) == pytest.approx(expected, abs=1e-3)
