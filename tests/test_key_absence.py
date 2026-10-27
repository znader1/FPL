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


def test_placebo_is_every_nonkey_regular_outfield_starter():
    rows = []
    for f in (1, 2, 3, 4):
        rows += [_row(1, 1, f, 90, 0.0, etype=1, event=f),      # GK: excluded
                 _row(2, 1, f, 90, 0.0, event=f),               # key: excluded
                 _row(3, 1, f, 90, 0.0, event=f)]               # regular: placebo
    rows += [_row(4, 1, 1, 90, 0.0, event=1)]                   # 1 start of 4: not regular
    rows += [_row(5, 1, f, 90, 0.0, event=f) for f in (1, 2)]   # 2 of 4 = 50%: regular
    df = pd.DataFrame(rows)
    team_fx = pd.DataFrame({"team_id": [1] * 4, "fixture": [1, 2, 3, 4], "event": [1, 2, 3, 4],
                            "was_home": True, "team_xg_for": 1.0})
    assert key_absence.select_placebo(df, {1: [2]}, team_fx) == {1: [3, 5]}


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


# --- Task 6: signals, overrides, run_analysis -----------------------------

def _boot(elements, teams=None):
    teams = teams or [{"id": 1, "short_name": "CHE"}, {"id": 2, "short_name": "ARS"}]
    return {"elements": elements, "teams": teams}


def _el(pid, team, code, name, etype=3, now_cost=60, threat=100, creativity=50,
        minutes=900, total_points=40):
    return {"id": pid, "team": team, "code": code, "web_name": name, "element_type": etype,
            "now_cost": now_cost, "threat": str(threat), "creativity": str(creativity),
            "minutes": minutes, "total_points": total_points}


def test_build_signals_joins_last_season_on_code():
    boot = _boot([_el(10, 1, 777, "Palmer", total_points=40), _el(11, 1, 888, "Nobody", total_points=10)])
    df = pd.DataFrame([_row(10, 1, 1, 90, 0.5), _row(10, 1, 2, 90, 0.5), _row(11, 1, 1, 90, 0.0)])
    last_boot = _boot([_el(99, 1, 777, "Palmer")])   # id reissued: 99 last season
    last_df = pd.DataFrame([_row(99, 1, f, 90, 0.2) for f in range(1, 13)]).assign(total_points=6)
    sig = key_absence.build_signals(df, boot, last_df, last_boot)
    p = sig[sig["player_id"] == 10].iloc[0]
    assert p["this_ppg"] == 20.0                    # 40 pts / 2 appearances
    assert abs(p["last_ppg"] - 6.0) < 1e-9          # 12 apps of 6
    assert math.isnan(sig[sig["player_id"] == 11].iloc[0]["last_ppg"])
    assert p["threat"] == 100.0 and p["now_cost"] == 60 and p["team_id"] == 1


def test_build_signals_from_history_uses_file_columns():
    raw = pd.DataFrame([
        dict(_row(10, 1, 1, 90, 0.5), threat=30.0, creativity=10.0, value=70, total_points=8),
        dict(_row(10, 1, 2, 90, 0.5), threat=20.0, creativity=10.0, value=72, total_points=2),
    ])
    sig = key_absence.build_signals_from_history(raw)
    p = sig.iloc[0]
    assert p["threat"] == 50.0 and p["creativity"] == 20.0 and p["now_cost"] == 72
    assert p["this_ppg"] == 5.0 and p["minutes"] == 180 and math.isnan(p["last_ppg"])


def test_parse_overrides_accent_insensitive_and_errors():
    boot = _boot([_el(10, 1, 1, "João Pedro"), _el(11, 1, 2, "Palmer"), _el(20, 2, 3, "Saka")])
    short = {1: "CHE", 2: "ARS"}
    assert key_absence.parse_overrides("CHE:Joao Pedro,Palmer;ARS:Saka", boot, short) == {1: [10, 11], 2: [20]}
    assert key_absence.parse_overrides(None, boot, short) == {}
    with pytest.raises(ValueError, match="CHE.*Nobody"):
        key_absence.parse_overrides("CHE:Nobody", boot, short)


def test_run_analysis_end_to_end_synthetic():
    rows, fixtures = [], []
    fid = 0
    for f in (1, 2, 3, 4):
        fid += 1
        fixtures.append(_fx(fid, 1, 2, event=f))
        rows += _team_block(1, fid, start=1000 * fid, event=f)
        rows += _team_block(2, fid, start=1000 * fid + 50, event=f)
        if f <= 2:
            rows.append(_row(10, 1, fid, 90, 0.6, event=f))   # key on team 1 absent for 3,4
        rows.append(_row(20, 2, fid, 90, 0.3, event=f))        # key on team 2 always present
    df = pd.DataFrame(rows)
    ratings = {"_league": 1.4, 1: {"attack": 1.0, "defense": 1.0}, 2: {"attack": 1.0, "defense": 1.0}}
    key = {1: [10], 2: [20]}
    placebo = {1: [1001], 2: [1051]}
    names = {10: "Key1", 20: "Key2", 1001: "P1", 1051: "P2"}
    res = key_absence.run_analysis(df, fixtures, ratings, key, placebo, {1: "CHE", 2: "ARS"}, names)
    assert len(res["team_rows"]) == 2
    r1 = next(r for r in res["team_rows"] if r["player_id"] == 10)
    assert r1["team_short"] == "CHE" and r1["player_name"] == "Key1"
    assert r1["n_present"] == 2 and r1["n_absent"] == 2
    assert "shrunk_teammates_effect" in r1
    assert res["key_pool"]["pairs"] == 1
    assert len(res["placebo_rows"]) == 2
    assert isinstance(res["decision"], tuple)
    assert all("team_short" in t and "key_player_name" in t for t in res["teammate_rows"])


# --- Task 7: report ---------------------------------------------------------

def test_render_report_contains_decision_and_team_row():
    result = {
        "team_rows": [{"team_id": 1, "team_short": "CHE", "player_id": 10, "player_name": "Joao Pedro",
                       "n_present": 6, "n_absent": 2, "n_benched": 0,
                       "teammates_effect": 0.62, "shrunk_teammates_effect": 0.80, "team_effect": 0.55,
                       "teammates_ratio_present": 1.1, "teammates_ratio_absent": 0.7,
                       "xg_for_present": 2.0, "xg_for_absent": 0.9}],
        "teammate_rows": [{"team_short": "CHE", "key_player_name": "Joao Pedro", "teammate_name": "Palmer",
                           "teammate_id": 11, "min_present": 540, "min_absent": 180,
                           "xg90_present": 0.5, "xg90_absent": 0.2, "xa90_present": 0.3, "xa90_absent": 0.1,
                           "xg90_ratio": 0.4, "xa90_ratio": 0.33}],
        "placebo_rows": [],
        "key_pool": {"effect": 0.88, "lo": 0.80, "hi": 0.95, "n": 40.0, "pairs": 30},
        "placebo_pool": {"effect": 1.01, "lo": 0.9, "hi": 1.1, "n": 30.0, "pairs": 20},
        "decision": (True, "key pooled 0.880 [0.800, 0.950] vs placebo 1.010: placebo outside interval, below bar 0.95"),
    }
    md = key_absence.render_report(result, "2026-27", {1: [10]}, {10: "Joao Pedro"}, {1: "CHE"},
                                   ["absence is inferred"])
    assert "placebo outside interval" in md
    assert "| CHE | Joao Pedro | 6 | 2 | 0 |" in md
    assert "Palmer" in md and "absence is inferred" in md
    assert "PASS" in md
