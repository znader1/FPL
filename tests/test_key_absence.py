"""Key-player absence analysis (src/key_absence.py) on synthetic frames."""
import math

import pandas as pd
import pytest

from src import key_absence


def _row(element, team, fixture, minutes, xg, xa=0.0, starts=None, event=1,
         was_home=True, etype=3, kickoff="2026-08-21T19:00:00Z"):
    if starts is None:
        starts = 1 if minutes >= 60 else 0
    return {
        "element": element, "element_type": etype, "team_id": team,
        "fixture": fixture, "event": event, "was_home": was_home,
        "kickoff_time": kickoff, "minutes": minutes, "starts": starts,
        "expected_goals": xg, "expected_assists": xa,
    }


def _fx(fid, home, away, event=1):
    return {"id": fid, "team_h": home, "team_a": away, "event": event}


# --- Task 1: loader ---------------------------------------------------------

def test_normalize_drops_rows_outside_fixture_pair():
    fixtures = [_fx(1, 1, 2)]
    df = pd.DataFrame([
        {"element": 10, "element_type": 4, "team_id": 1, "fixture": 1, "event": 1, "was_home": True,
         "kickoff_time_x": "2026-08-21T19:00:00Z", "minutes": 90, "starts": 1,
         "expected_goals": 0.5, "expected_assists": 0.1},
        {"element": 11, "element_type": 4, "team_id": 3, "fixture": 1, "event": 1, "was_home": False,
         "kickoff_time_x": "2026-08-21T19:00:00Z", "minutes": 90, "starts": 1,
         "expected_goals": 0.5, "expected_assists": 0.1},
    ])
    out = key_absence.normalize_history(df, fixtures)
    assert out["element"].tolist() == [10]
    assert "kickoff_time" in out.columns and "kickoff_time_x" not in out.columns


def test_team_fixture_sets_requires_eleven_players():
    rows = [_row(e, team=1, fixture=1, minutes=90, xg=0.1) for e in range(11)]
    rows += [_row(e, team=2, fixture=1, minutes=90, xg=0.1) for e in range(100, 105)]
    out = key_absence.team_fixture_sets(pd.DataFrame(rows))
    assert out["team_id"].tolist() == [1]
    assert abs(out["team_xg_for"].iloc[0] - 1.1) < 1e-9
    assert set(out.columns) >= {"team_id", "fixture", "event", "was_home", "team_xg_for"}


# --- Task 2: presence buckets ---------------------------------------------

def _team_block(team, fixture, start=0, n=11, xg=0.1, event=None):
    """Eleven filler starters so the fixture counts as played."""
    return [_row(start + i, team=team, fixture=fixture, minutes=90, xg=xg,
                 event=event or fixture) for i in range(n)]


def _three_fixture_frame(key_rows):
    rows = []
    for f in (1, 2, 3):
        rows += _team_block(1, f, start=1000 * f)
    rows += key_rows
    df = pd.DataFrame(rows)
    return df, key_absence.team_fixture_sets(df)


def test_absent_inferred_from_zero_minute_row():
    df, team_fx = _three_fixture_frame([
        _row(10, 1, 1, 90, 0.5, event=1),
        _row(10, 1, 2, 0, 0.0, event=2),
        _row(10, 1, 3, 90, 0.5, event=3),
    ])
    out = key_absence.presence_buckets(df, team_fx, team_id=1, player_id=10)
    assert dict(zip(out["fixture"], out["bucket"])) == {1: "present", 2: "absent", 3: "present"}
    assert dict(zip(out["fixture"], out["key_xg"])) == {1: 0.5, 2: 0.0, 3: 0.5}


def test_absent_inferred_from_missing_row():
    df, team_fx = _three_fixture_frame([
        _row(10, 1, 1, 90, 0.5, event=1),
        _row(10, 1, 3, 90, 0.5, event=3),
    ])
    out = key_absence.presence_buckets(df, team_fx, team_id=1, player_id=10)
    assert dict(zip(out["fixture"], out["bucket"]))[2] == "absent"


def test_benched_bucket():
    df, team_fx = _three_fixture_frame([
        _row(10, 1, 1, 90, 0.5, event=1),
        _row(10, 1, 2, 20, 0.1, starts=0, event=2),
        _row(10, 1, 3, 90, 0.5, event=3),
    ])
    out = key_absence.presence_buckets(df, team_fx, team_id=1, player_id=10)
    assert dict(zip(out["fixture"], out["bucket"]))[2] == "benched"


def test_moved_player_fixtures_before_first_appearance_excluded():
    df, team_fx = _three_fixture_frame([_row(10, 1, 3, 90, 0.5, event=3)])
    out = key_absence.presence_buckets(df, team_fx, team_id=1, player_id=10)
    assert out["fixture"].tolist() == [3]


# --- Task 3: selection ------------------------------------------------------

def _sig(pid, team, etype=3, minutes=900, threat=100.0, creativity=100.0,
         now_cost=60, last_ppg=4.0, this_ppg=4.0):
    return {"player_id": pid, "team_id": team, "element_type": etype, "minutes": minutes,
            "threat": threat, "creativity": creativity, "now_cost": now_cost,
            "last_ppg": last_ppg, "this_ppg": this_ppg}


def test_select_excludes_gk_and_returns_top_n():
    sig = pd.DataFrame([
        _sig(1, 1, etype=1, threat=999, creativity=999, now_cost=99, last_ppg=9, this_ppg=9),
        _sig(2, 1, threat=300), _sig(3, 1, threat=200), _sig(4, 1, threat=100), _sig(5, 1, threat=50),
    ])
    out = key_absence.select_key_players(sig, top=3)
    assert out == {1: [2, 3, 4]}


def test_select_rate_not_total():
    # B has half the minutes and half the threat: same rate, must still rank above C.
    sig = pd.DataFrame([
        _sig(1, 1, minutes=900, threat=300, creativity=300),
        _sig(2, 1, minutes=450, threat=150, creativity=150),
        _sig(3, 1, minutes=900, threat=100, creativity=100),
        _sig(4, 1, minutes=900, threat=10, creativity=10, now_cost=40, last_ppg=1, this_ppg=1),
    ])
    out = key_absence.select_key_players(sig, top=2)
    assert out == {1: [1, 2]}


def test_select_short_team_returns_what_it_has():
    sig = pd.DataFrame([_sig(1, 1, etype=1), _sig(2, 1), _sig(3, 1)])
    assert key_absence.select_key_players(sig, top=3) == {1: [2, 3]}


def test_override_replaces_list():
    sig = pd.DataFrame([_sig(2, 1, threat=300), _sig(3, 1), _sig(4, 1)])
    assert key_absence.select_key_players(sig, top=3, overrides={1: [4]}) == {1: [4]}


def test_placebo_excludes_keys_and_gk():
    rows = [_row(1, 1, 1, 90, 0.0, etype=1), _row(2, 1, 1, 90, 0.0), _row(3, 1, 1, 60, 0.0),
            _row(4, 1, 1, 30, 0.0)]
    df = pd.DataFrame(rows)
    assert key_absence.select_placebo(df, {1: [2]}) == {1: 3}
