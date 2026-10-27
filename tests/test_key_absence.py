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


# --- Task 4: team effect ----------------------------------------------------

RATINGS = {
    "_league": 1.4,
    1: {"attack": 1.0, "defense": 1.0},
    2: {"attack": 1.0, "defense": 0.6},   # tight
    3: {"attack": 1.0, "defense": 1.4},   # leaky
}


def _buckets(rows):
    return pd.DataFrame(rows, columns=["team_id", "fixture", "event", "was_home",
                                       "team_xg_for", "bucket", "key_xg"])


def test_ratio_controls_for_opponent():
    from src import fixture_difficulty as fd
    leaky_exp, _ = fd.expected_xg_for_fixture(RATINGS, 1, 3, True)
    tight_exp, _ = fd.expected_xg_for_fixture(RATINGS, 1, 2, True)
    fixtures = [_fx(1, 1, 3), _fx(2, 1, 2)]
    b = _buckets([
        (1, 1, 1, True, leaky_exp, "present", 0.0),   # vs leaky, key scored nothing himself
        (1, 2, 2, True, tight_exp, "absent", 0.0),    # vs tight
    ])
    out = key_absence.attach_expected(b, RATINGS, fixtures)
    assert out["opp_id"].tolist() == [3, 2]
    eff = key_absence.team_effect(out)
    assert out["team_xg_for"].iloc[1] < out["team_xg_for"].iloc[0]   # raw xG lower when absent
    assert abs(eff["teammates_effect"] - 1.0) < 1e-6


def test_n_absent_zero_gives_nan_effect_not_error():
    b = key_absence.attach_expected(
        _buckets([(1, 1, 1, True, 1.4, "present", 0.3)]), RATINGS, [_fx(1, 1, 2)])
    eff = key_absence.team_effect(b)
    assert eff["n_absent"] == 0 and eff["n_present"] == 1
    assert math.isnan(eff["teammates_effect"]) and math.isnan(eff["team_effect"])


def test_teammates_effect_ignores_key_players_own_xg():
    fixtures = [_fx(1, 1, 2), _fx(2, 1, 2)]
    b = _buckets([
        (1, 1, 1, True, 2.0, "present", 1.0),   # key made 1.0, teammates 1.0
        (1, 2, 2, True, 1.0, "absent", 0.0),    # teammates still 1.0
    ])
    eff = key_absence.team_effect(key_absence.attach_expected(b, RATINGS, fixtures))
    assert abs(eff["teammates_effect"] - 1.0) < 1e-9
    assert eff["team_effect"] < 1.0
    assert eff["n_benched"] == 0


# --- Task 5: teammate rates, pooling, shrinkage, decision ------------------

def test_teammate_rates_minutes_weighted():
    rows = []
    for f in (1, 2, 3, 4):
        rows += _team_block(1, f, start=1000 * f, n=10)
    # key player 10 present in 1,2; absent 3,4
    rows += [_row(10, 1, 1, 90, 0.5, event=1), _row(10, 1, 2, 90, 0.5, event=2)]
    # teammate 20: present 2x90 with xa 0.1; absent 10 min xa 1.0 + 170 min xa 0
    rows += [_row(20, 1, 1, 90, 0.0, xa=0.1, event=1), _row(20, 1, 2, 90, 0.0, xa=0.1, event=2),
             _row(20, 1, 3, 10, 0.0, xa=1.0, event=3), _row(20, 1, 4, 170, 0.0, xa=0.0, event=4)]
    df = pd.DataFrame(rows)
    team_fx = key_absence.team_fixture_sets(df)
    b = key_absence.presence_buckets(df, team_fx, 1, 10)
    out = key_absence.teammate_rates(df, b, 1, 10)
    r = out[out["teammate_id"] == 20].iloc[0]
    assert abs(r["xa90_present"] - 0.1) < 1e-9
    assert abs(r["xa90_absent"] - 0.5) < 1e-9
    assert abs(r["xa90_ratio"] - 5.0) < 1e-9
    assert r["min_present"] == 180 and r["min_absent"] == 180


def test_teammate_below_threshold_excluded():
    rows = []
    for f in (1, 2):
        rows += _team_block(1, f, start=1000 * f, n=10)
    rows += [_row(10, 1, 1, 90, 0.5, event=1)]
    rows += [_row(20, 1, 1, 90, 0.0, event=1), _row(20, 1, 2, 90, 0.0, event=2)]  # 90 each: under 180
    df = pd.DataFrame(rows)
    b = key_absence.presence_buckets(df, key_absence.team_fixture_sets(df), 1, 10)
    out = key_absence.teammate_rates(df, b, 1, 10)
    assert 20 not in out["teammate_id"].tolist()


def test_pool_weights_by_n_absent_and_skips_nan():
    rows = [{"teammates_effect": 0.5, "n_absent": 1}, {"teammates_effect": 1.0, "n_absent": 3},
            {"teammates_effect": float("nan"), "n_absent": 5}, {"teammates_effect": 9.0, "n_absent": 0}]
    p = key_absence.pool_effects(rows)
    assert abs(p["effect"] - 0.875) < 1e-9
    assert p["n"] == 4 and p["pairs"] == 2
    assert p["lo"] <= p["effect"] <= p["hi"]


def test_shrink_formula():
    assert key_absence.shrink(0.5, 4, 1.0) == 0.75
    assert key_absence.shrink(float("nan"), 4, 1.0) == 1.0


def test_decision_rule():
    assert key_absence.decision({"effect": 0.85, "lo": 0.80, "hi": 0.90}, {"effect": 1.0})[0] is True
    assert key_absence.decision({"effect": 0.85, "lo": 0.70, "hi": 1.05}, {"effect": 1.0})[0] is False
    assert key_absence.decision({"effect": 0.97, "lo": 0.96, "hi": 0.98}, {"effect": 1.0})[0] is False


def test_long_term_injury_after_last_appearance_counts_absent():
    df, team_fx = _three_fixture_frame([_row(10, 1, 1, 90, 0.5, event=1)])
    out = key_absence.presence_buckets(df, team_fx, team_id=1, player_id=10)
    assert dict(zip(out["fixture"], out["bucket"])) == {1: "present", 2: "absent", 3: "absent"}


def test_sold_player_fixtures_after_move_excluded():
    rows = []
    for f in (1, 2, 3):
        rows += _team_block(1, f, start=1000 * f)
    rows += _team_block(2, 4, start=4000)
    rows += [_row(10, 1, 1, 90, 0.5, event=1), _row(10, 2, 4, 90, 0.5, event=4)]  # moved to team 2
    df = pd.DataFrame(rows)
    out = key_absence.presence_buckets(df, key_absence.team_fixture_sets(df), team_id=1, player_id=10)
    assert out["fixture"].tolist() == [1]
