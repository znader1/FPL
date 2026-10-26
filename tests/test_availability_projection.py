import pandas as pd
import pytest

from src import availability as av
from src import config, fixture_difficulty, projections
from src.config_overrides import config_overrides


def _elements(striker_status="a"):
    rows = [
        # id, team, type, status
        (9, 1, 4, striker_status), (8, 1, 3, "a"), (7, 1, 3, "a"), (1, 1, 1, "a"), (2, 1, 2, "a"),
        (29, 2, 4, "a"), (28, 2, 3, "a"), (21, 2, 1, "a"), (20, 2, 2, "a"),
    ]
    df = pd.DataFrame(rows, columns=["id", "team", "element_type", "status"])
    df["web_name"] = df["id"].map(lambda i: f"P{i}")
    df["now_cost"] = 60
    df["points_per_game"] = 4.0
    df["form"] = 4.0
    df["minutes"] = 540
    df["total_points"] = 24
    df["chance_of_playing_next_round"] = None
    return df


def _matches():
    rows = []
    shares = {9: (0.5, 0.1), 8: (0.3, 0.2), 7: (0.4, 0.5), 1: (0, 0), 2: (0, 0),
              29: (0.5, 0.1), 28: (0.3, 0.2), 21: (0, 0), 20: (0, 0)}
    team = {9: 1, 8: 1, 7: 1, 1: 1, 2: 1, 29: 2, 28: 2, 21: 2, 20: 2}
    etype = {9: 4, 8: 3, 7: 3, 1: 1, 2: 2, 29: 4, 28: 3, 21: 1, 20: 2}
    for ev in range(3, 9):
        for el, (xg, xa) in shares.items():
            rows.append({"element": el, "team_id": team[el], "element_type": etype[el], "event": ev,
                         "fixture": ev * 10 + team[el], "was_home": team[el] == 1,
                         "kickoff_time": f"2026-09-{ev + 10:02d}T15:00:00Z", "minutes": 90,
                         "expected_goals": xg, "expected_assists": xa, "expected_goals_conceded": 1.0,
                         "defensive_contribution": 0, "saves": 0, "total_points": 3, "bps": 10, "starts": 1})
    return pd.DataFrame(rows)


FIXTURES = pd.DataFrame([(9, 1, 2, 3, 3)], columns=["event", "team_h", "team_a", "team_h_difficulty", "team_a_difficulty"])
SHORT = {1: "AAA", 2: "BBB"}


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(fixture_difficulty, "load_match_history", lambda *a, **k: _matches())
    yield


def _project(striker_status, **overrides):
    with config_overrides(overrides):
        return projections.project_elements_next_gws(
            elements=_elements(striker_status), fixtures=FIXTURES, teams_short_map=SHORT,
            gw_start=9, horizon_gws=1).set_index("id")


def test_disabled_never_touches_projections(patched, monkeypatch):
    calls = {"n": 0}
    for name in ("team_shares", "team_missing", "apply_to_ratings", "teammate_multiplier"):
        real = getattr(av, name)

        def spy(*a, _real=real, **k):
            calls["n"] += 1
            return _real(*a, **k)

        monkeypatch.setattr(av, name, spy)
    a = _project("s", AVAIL_ENABLED=False)
    b = _project("s", AVAIL_ENABLED=False)
    assert calls["n"] == 0
    assert (a["avail_teammate_mult"] == 1.0).all()
    assert a["xpts_gw9"].equals(b["xpts_gw9"])


def test_striker_out_lowers_teammates_and_weakens_his_team_for_opponents(patched, monkeypatch):
    seen = []
    real = av.apply_to_ratings

    def spy(ratings, missing):
        seen.append(missing)
        return real(ratings, missing)

    monkeypatch.setattr(av, "apply_to_ratings", spy)
    base = {"PROJ_DIFFICULTY_SOURCE": "xg_ratings", "PROJ_MODEL_BLEND_WEIGHT": 0.5}
    fit = _project("a", **base)
    seen.clear()
    out = _project("s", **base)
    assert out.loc[8, "xpts_gw9"] < fit.loc[8, "xpts_gw9"]         # teammate midfielder drops
    assert abs(out.loc[8, "avail_teammate_mult"] - (1 - config.AVAIL_TEAMMATE_IMPACT * 0.30)) < 1e-9
    assert out.loc[28, "avail_teammate_mult"] == 1.0                # the other team's attackers untouched
    assert out.loc[20, "diff_avg_gw9"] == fit.loc[20, "diff_avg_gw9"]   # xG difficulty path did not fall back
    # Team 1's lowered attack reaches the ratings opponents are projected against.
    assert seen and all(abs(m[1]["attack"] - 0.30) < 1e-9 for m in seen)


def test_failure_falls_back(patched, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("availability broke")

    monkeypatch.setattr(av, "team_shares", boom)
    out = _project("s")
    assert (out["avail_teammate_mult"] == 1.0).all()
    assert out["xpts_gw9"].notna().all()
