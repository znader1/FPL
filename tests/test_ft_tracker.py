from src.ft_tracker import derive_free_transfers, clamp_ft


def _ev(event, used):
    return {"event": event, "event_transfers": used}


def test_gw1_no_history_gives_one():
    assert derive_free_transfers([], [], next_event_id=1) == 1


def test_gw2_always_one_ft_regardless_of_gw1():
    # GW1 is squad creation — no FT accrues from it. Entering GW2 = exactly 1 FT.
    assert derive_free_transfers([_ev(1, 0)], [], next_event_id=2) == 1
    assert derive_free_transfers([_ev(1, 5)], [], next_event_id=2) == 1


def test_unused_fts_bank_up_to_cap():
    # Zero transfers GW1-6: GW1 skipped; after GW2 -> 2, GW3 -> 3, GW4 -> 4,
    # GW5 -> 5, GW6 -> 5 (capped)
    events = [_ev(g, 0) for g in range(1, 7)]
    assert derive_free_transfers(events, [], next_event_id=7) == 5


def test_spending_reduces_bank():
    # Entering GW2 with 1 FT; GW2 uses 2 (a hit) -> min(5, max(1-2,0)+1) = 1 at GW3;
    # GW3 uses 0 -> 2 at GW4
    events = [_ev(1, 0), _ev(2, 2), _ev(3, 0)]
    assert derive_free_transfers(events, [], next_event_id=4) == 2


def test_hits_floor_at_one():
    # Using more transfers than held (hits) still leaves 1 FT next GW
    events = [_ev(1, 0), _ev(2, 4)]
    assert derive_free_transfers(events, [], next_event_id=3) == 1


def test_wildcard_gw_maintains_the_bank():
    # WC in GW3 with 8 transfers: nothing spent, nothing gained — the 2 FT
    # taken into GW3 are still 2 for GW4, then GW4 unused banks a third.
    events = [_ev(1, 0), _ev(2, 0), _ev(3, 8), _ev(4, 0)]
    chips = [{"name": "wildcard", "event": 3}]
    assert derive_free_transfers(events, chips, next_event_id=5) == 3


def test_freehit_gw_maintains_the_bank():
    # FH in GW2 with 1 FT: still 1 FT for GW3 (maintained, no +1).
    events = [_ev(1, 0), _ev(2, 1)]
    chips = [{"name": "freehit", "event": 2}]
    assert derive_free_transfers(events, chips, next_event_id=3) == 1


def test_live_shape_fh_after_two_single_transfers():
    # Entry 5645321 on 2026-09-18: 1 transfer in GW2, 1 in GW3, Free Hit in
    # GW4 -> FPL shows 1 free transfer for GW5.
    events = [_ev(1, 0), _ev(2, 1), _ev(3, 1), _ev(4, 0)]
    chips = [{"name": "freehit", "event": 4}]
    assert derive_free_transfers(events, chips, next_event_id=5) == 1


def test_events_at_or_after_next_are_ignored():
    events = [_ev(1, 0), _ev(2, 3)]  # GW2 row present but next_event_id=2 -> ignore it
    assert derive_free_transfers(events, [], next_event_id=2) == 1


def test_clamp_ft():
    assert clamp_ft(0) == 1
    assert clamp_ft(3) == 3
    assert clamp_ft(9) == 5
    assert clamp_ft(None) is None
    assert clamp_ft("2") == 2


def test_runtime_config_override(monkeypatch):
    # Verify that config.FT_MAX is read at call time, not import time.
    from src import config
    monkeypatch.setattr(config, "FT_MAX", 3)
    assert clamp_ft(9) == 3
    assert derive_free_transfers(
        [_ev(1, 0), _ev(2, 0), _ev(3, 0), _ev(4, 0)], [], next_event_id=5
    ) == 3
