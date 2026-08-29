"""Match history built from /event/{gw}/live/ — the file the xG model reads."""
import pandas as pd
import pytest

from src import fixture_difficulty, live_history, output_model


BOOTSTRAP = {
    "events": [
        {"id": 1, "finished": True},
        {"id": 2, "finished": True},
        {"id": 3, "finished": False},   # in progress: ICT columns still zeroed
    ],
    "elements": [
        {"id": 10, "team": 1, "element_type": 4},   # FWD, team 1
        {"id": 20, "team": 2, "element_type": 2},   # DEF, team 2
        {"id": 30, "team": 1, "element_type": 3},   # MID, team 1
    ],
}

FIXTURES = pd.DataFrame([
    {"id": 100, "event": 2, "team_h": 1, "team_a": 2, "kickoff_time": "2026-08-28T17:30:00Z"},
    {"id": 101, "event": 2, "team_h": 2, "team_a": 1, "kickoff_time": "2026-08-29T14:00:00Z"},
])


def _el(pid, minutes, xg, xa=0.0, fixtures=(100,), mins_split=None):
    explain = []
    for fid in fixtures:
        m = mins_split.get(fid) if mins_split else minutes
        explain.append({"fixture": fid,
                        "stats": [{"identifier": "minutes", "value": m, "points": 1}]})
    return {
        "id": pid,
        "stats": {"minutes": minutes, "expected_goals": xg, "expected_assists": xa,
                  "expected_goals_conceded": 1.0, "defensive_contribution": 8,
                  "saves": 0, "total_points": 6, "bps": 20, "starts": 1},
        "explain": explain,
    }


def test_builds_a_row_per_player_fixture_with_the_columns_the_model_reads():
    rows = live_history.build_event_rows([_el(10, 90, 0.75)], BOOTSTRAP, FIXTURES, 2)
    assert len(rows) == 1
    r = rows.iloc[0]
    assert r["element"] == 10 and r["team_id"] == 1 and r["fixture"] == 100
    assert r["event"] == 2 and r["element_type"] == 4
    assert r["expected_goals"] == pytest.approx(0.75)
    assert bool(r["was_home"]) is True   # team 1 is team_h in fixture 100


def test_away_players_are_marked_away():
    rows = live_history.build_event_rows([_el(20, 90, 0.1)], BOOTSTRAP, FIXTURES, 2)
    assert bool(rows.iloc[0]["was_home"]) is False


def test_players_who_did_not_appear_are_dropped():
    # A zero-minute row contributes nothing to a per-90 rate and would only
    # dilute the weighted minutes denominator.
    assert live_history.build_event_rows([_el(10, 0, 0.0)], BOOTSTRAP, FIXTURES, 2).empty


def test_double_gameweek_splits_by_minutes_and_conserves_the_total():
    el = _el(30, 120, 1.20, fixtures=(100, 101), mins_split={100: 90, 101: 30})
    rows = live_history.build_event_rows([el], BOOTSTRAP, FIXTURES, 2)
    assert len(rows) == 2
    assert rows["expected_goals"].sum() == pytest.approx(1.20)
    by_fx = dict(zip(rows["fixture"], rows["expected_goals"]))
    assert by_fx[100] == pytest.approx(0.90)   # 90/120 of the total
    assert by_fx[101] == pytest.approx(0.30)


def test_unknown_players_and_fixtures_are_skipped_not_fatal():
    stray = _el(999, 90, 0.5)                  # not in bootstrap
    bad_fx = _el(10, 90, 0.5, fixtures=(555,))  # fixture not in the list
    rows = live_history.build_event_rows([stray, bad_fx], BOOTSTRAP, FIXTURES, 2)
    assert rows.empty


def test_only_finished_gameweeks_are_recorded():
    # GW3 is in progress: its xG can still change and its ICT columns read 0.
    assert live_history.finished_event_ids(BOOTSTRAP) == [1, 2]


def test_missing_events_skips_what_is_already_on_disk():
    existing = pd.DataFrame([{"event": 1, "element": 10, "fixture": 1}])
    assert live_history.missing_event_ids(existing, BOOTSTRAP) == [2]
    assert live_history.missing_event_ids(None, BOOTSTRAP) == [1, 2]


def test_append_survives_a_gameweek_that_fails_upstream():
    def _fetch(gw):
        if gw == 1:
            raise RuntimeError("upstream 503")
        return [_el(10, 90, 0.75)]

    out, added = live_history.append_events(None, BOOTSTRAP, FIXTURES, [1, 2], fetch=_fetch)
    assert added == [2]
    assert len(out) == 1


def test_appending_the_same_gameweek_twice_does_not_duplicate():
    fetch = lambda gw: [_el(10, 90, 0.75)]
    first, _ = live_history.append_events(None, BOOTSTRAP, FIXTURES, [2], fetch=fetch)
    second, _ = live_history.append_events(first, BOOTSTRAP, FIXTURES, [2], fetch=fetch)
    assert len(second) == 1


def test_output_feeds_the_xg_stack_end_to_end():
    """The point of the file: team ratings and player rates must come out of it."""
    fetch = lambda gw: [_el(10, 90, 0.90), _el(20, 90, 0.10), _el(30, 90, 0.40)]
    hist, _ = live_history.append_events(None, BOOTSTRAP, FIXTURES, [2], fetch=fetch)

    team_xg = fixture_difficulty.build_team_match_xg(hist)
    assert not team_xg.empty, "team xG must be derivable from the built history"
    # Team 1 (0.90 + 0.40) out-created team 2 (0.10) in fixture 100.
    t1 = team_xg[team_xg["team_id"] == 1].iloc[0]
    assert t1["xg_for"] == pytest.approx(1.30)
    assert t1["xg_against"] == pytest.approx(0.10)

    rates = output_model.compute_player_rates(hist, gw=3)
    assert not rates.empty, "player per-90 rates must be derivable from the built history"
    assert set(["player_id", "xg90", "xa90", "minutes_sample"]).issubset(rates.columns)


def test_refresh_writes_the_file_the_model_reads(tmp_path, monkeypatch):
    """
    The whole point of #52: a deployed server must be able to produce
    player_match_history without a developer's laptop.
    """
    from api import main as api_main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api_main, "season_label_from_bootstrap", lambda b: "2026-27")
    monkeypatch.setattr(
        api_main.live_history, "append_events",
        lambda existing, boot, fx, ids, **kw: (
            pd.DataFrame([{"element": 10, "fixture": 100, "event": 2, "expected_goals": 0.9}]),
            list(ids),
        ),
    )

    info = api_main.refresh_match_history(BOOTSTRAP, FIXTURES)
    written = tmp_path / "data/processed/fpl/2026-27/player_match_history_2026-27.csv"
    assert written.exists(), "the model's input file must land on disk"
    assert info["appended_events"] == [1, 2]
    assert info["rows"] == 1


def test_refresh_is_a_no_op_once_current(tmp_path, monkeypatch):
    from api import main as api_main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api_main, "season_label_from_bootstrap", lambda b: "2026-27")
    out = tmp_path / "data/processed/fpl/2026-27"
    out.mkdir(parents=True)
    pd.DataFrame([
        {"element": 10, "fixture": 100, "event": 1},
        {"element": 10, "fixture": 101, "event": 2},
    ]).to_csv(out / "player_match_history_2026-27.csv", index=False)

    monkeypatch.setattr(
        api_main.live_history, "append_events",
        lambda *a, **k: pytest.fail("must not fetch when the history is already current"),
    )
    info = api_main.refresh_match_history(BOOTSTRAP, FIXTURES)
    assert info["appended_events"] == []
    assert info["note"] == "already current"
