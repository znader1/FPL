import pandas as pd

from src.chip_advisor import chip_windows, team_fixture_counts


def test_chip_windows_all_available_when_none_played():
    w = chip_windows([], current_gw=5)
    assert set(w) == {"wildcard", "free_hit", "bench_boost", "triple_captain"}
    assert all(v["available"] for v in w.values())
    assert all(v["half"] == 1 and v["expires_gw"] == 19 for v in w.values())


def test_chip_windows_played_chip_unavailable_in_phase():
    played = [{"name": "bboost", "event": 4}]
    w = chip_windows(played, current_gw=6)
    assert w["bench_boost"]["available"] is False
    assert w["wildcard"]["available"] is True


def test_chip_windows_phase1_play_resets_in_phase2():
    played = [{"name": "3xc", "event": 10}]
    w = chip_windows(played, current_gw=25)
    assert w["triple_captain"]["available"] is True
    assert w["triple_captain"]["half"] == 2
    assert w["triple_captain"]["expires_gw"] == 38


def test_chip_windows_current_gw_play_still_counts_as_available():
    # Advising FOR current_gw: a chip logged in current_gw isn't "gone" yet
    # (mirrors the strictly-before rule in the old _derive_chips_remaining).
    played = [{"name": "wildcard", "event": 7}]
    w = chip_windows(played, current_gw=7)
    assert w["wildcard"]["available"] is True


def test_chip_windows_normalizes_fpl_names():
    played = [{"name": "freehit", "event": 3}, {"name": "BBOOST", "event": 4}]
    w = chip_windows(played, current_gw=8)
    assert w["free_hit"]["available"] is False
    assert w["bench_boost"]["available"] is False


def _fixtures(rows):
    return pd.DataFrame(rows, columns=["event", "team_h", "team_a"])


def test_team_fixture_counts_single_and_double():
    fx = _fixtures([
        (12, 1, 2),
        (12, 1, 3),   # team 1 doubles in GW12
        (13, 2, 3),
    ])
    counts = team_fixture_counts(fx, 12)
    assert counts == {1: 2, 2: 1, 3: 1}


def test_team_fixture_counts_blank_gw_team_absent():
    fx = _fixtures([(12, 1, 2)])
    counts = team_fixture_counts(fx, 12)
    assert 3 not in counts
    assert counts.get(3, 0) == 0


def test_team_fixture_counts_empty_fixtures():
    assert team_fixture_counts(pd.DataFrame(columns=["event", "team_h", "team_a"]), 5) == {}
