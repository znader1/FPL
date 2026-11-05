import pandas as pd

from src import config
from src.season_replay import actuals_for_gw, build_live_engine_inputs, cap_match_history


def _bootstrap():
    elements = []
    for pid, team, etype in ((1, 1, 3), (2, 1, 4), (999, 2, 2)):
        row = {c: None for c in config.ELEMENTS_KEEP}
        row.update({
            "id": pid, "web_name": f"P{pid}", "team": team, "element_type": etype,
            "now_cost": 100, "status": "a", "chance_of_playing_next_round": None,
            "total_points": 999, "form": "9.9", "points_per_game": "9.9",
            "minutes": 9999, "starts": 99, "ep_next": "9.9", "selected_by_percent": "99.0",
            "expected_goals_per_90": 9.9, "expected_assists_per_90": 9.9,
            "expected_goals_conceded_per_90": 9.9, "saves_per_90": 9.9,
        })
        elements.append(row)
    return {
        "elements": elements,
        "teams": [{"id": 1, "name": "Alpha", "short_name": "ALP"},
                  {"id": 2, "name": "Beta", "short_name": "BET"}],
        "element_types": [{"id": i, "singular_name_short": s}
                          for i, s in ((1, "GKP"), (2, "DEF"), (3, "MID"), (4, "FWD"))],
    }


def _fixtures():
    return [{"event": g, "team_h": 1, "team_a": 2, "team_h_difficulty": 3,
             "team_a_difficulty": 3} for g in range(1, 12)]


def _history():
    rows = []
    for pid in (1, 2, 999):
        for gw in range(5, 10):
            pts = 20 if (pid == 1 and gw == 8) else 2
            rows.append({"player_id": pid, "gw": gw, "gw_total_points": pts,
                         "gw_minutes": 90, "gw_starts": 1, "gw_fixture_count": 1})
    return pd.DataFrame(rows)


def _snapshots():
    rows = []
    for gw in (6, 7):
        for pid in (1, 2):
            rows.append({"season": "2026-27", "gw": gw, "player_id": pid,
                         "price_m": 6.0 if gw == 6 else 6.2,
                         "status": "a" if gw == 6 else "d",
                         "chance": None if gw == 6 else 50,
                         "fpl_ep_next": 3.0, "ownership_pct": 12.5,
                         "actual_points": 4, "actual_minutes": 90})
    return pd.DataFrame(rows)


def _match():
    rows = []
    for ev in range(5, 9):
        rows.append({"element": 1, "event": ev, "team_id": 1, "minutes": 90,
                     "expected_goals": 1.0 if ev == 8 else 0.1, "expected_assists": 0.1,
                     "expected_goals_conceded": 1.0, "saves": 0})
    return pd.DataFrame(rows)


def _build(target=7, match_df=None):
    return build_live_engine_inputs(target, 1, _bootstrap(), _fixtures(), _history(),
                                    _snapshots(), match_df=match_df)


def test_no_future_history_leaks():
    elements, _, _, history_capped, _ = _build(7)
    assert history_capped["gw"].max() == 6
    p1 = elements.set_index("id").loc[1]
    # GW5-6 only: 2 + 2 points over two appearances; the GW8 haul is invisible.
    assert p1["total_points"] == 4
    assert p1["points_per_game"] == 2.0
    assert p1["form"] == 2.0
    assert p1["minutes"] == 180


def test_as_of_fields_come_from_target_gw_snapshot():
    elements, _, _, _, _ = _build(7)
    p1 = elements.set_index("id").loc[1]
    assert p1["now_cost"] == 62
    assert p1["status"] == "d"
    assert p1["chance_of_playing_next_round"] == 50
    assert p1["ep_next"] == 3.0
    assert p1["selected_by_percent"] == 12.5


def test_player_without_snapshot_is_dropped_not_defaulted():
    elements, _, _, _, dropped = _build(7)
    assert 999 not in set(elements["id"])
    assert 999 in dropped


def test_frame_has_every_engine_column():
    elements, _, _, _, _ = _build(7)
    assert set(config.ELEMENTS_KEEP) <= set(elements.columns)
    assert elements.set_index("id").loc[1, "starts"] == 2


def test_per90_rebuilt_from_matches_before_target_never_from_bootstrap():
    elements, _, _, _, _ = _build(7, match_df=_match())
    p1 = elements.set_index("id").loc[1]
    assert abs(p1["expected_goals_per_90"] - 0.1) < 1e-9  # GW5-6 only, not the GW8 1.0
    no_match, _, _, _, _ = _build(7)
    assert pd.isna(no_match.set_index("id").loc[1, "expected_goals_per_90"])


def test_cap_match_history_strictly_before_target():
    capped = cap_match_history(_match(), 7)
    assert capped["event"].max() == 6


def test_actuals_mark_blank_gw_as_no_fixture():
    hist = _history()
    hist.loc[(hist.player_id == 2) & (hist.gw == 7), "gw_fixture_count"] = 0
    act = actuals_for_gw(_snapshots(), hist, 7).set_index("player_id")
    assert bool(act.loc[1, "had_fixture"]) is True
    assert bool(act.loc[2, "had_fixture"]) is False
    assert act.loc[1, "actual"] == 4
