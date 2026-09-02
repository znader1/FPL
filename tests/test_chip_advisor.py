from src.chip_advisor import chip_windows


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
