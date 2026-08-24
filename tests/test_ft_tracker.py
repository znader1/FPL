from src.ft_tracker import derive_free_transfers, clamp_ft


def _ev(event, used):
    return {"event": event, "event_transfers": used}


def test_gw1_no_history_gives_one():
    assert derive_free_transfers([], [], next_event_id=1) == 1


def test_unused_fts_bank_up_to_cap():
    # 6 GWs of zero transfers: 1 -> 2 -> 3 -> 4 -> 5 -> 5 (capped)
    events = [_ev(g, 0) for g in range(1, 7)]
    assert derive_free_transfers(events, [], next_event_id=7) == 5


def test_spending_reduces_bank():
    # GW1 bank (0 used) -> 2 FT at GW2; GW2 uses 2 -> min(5, max(2-2,0)+1) = 1 at GW3
    events = [_ev(1, 0), _ev(2, 2)]
    assert derive_free_transfers(events, [], next_event_id=3) == 1


def test_hits_floor_at_one():
    # Using more transfers than held (hits) still leaves 1 FT next GW
    events = [_ev(1, 4)]
    assert derive_free_transfers(events, [], next_event_id=2) == 1


def test_wildcard_gw_consumes_nothing():
    # WC in GW2 with 8 transfers: treated as 0 used -> bank keeps growing
    events = [_ev(1, 0), _ev(2, 8), _ev(3, 0)]
    chips = [{"name": "wildcard", "event": 2}]
    assert derive_free_transfers(events, chips, next_event_id=4) == 4


def test_freehit_gw_consumes_nothing():
    events = [_ev(1, 0), _ev(2, 1)]
    chips = [{"name": "freehit", "event": 2}]
    assert derive_free_transfers(events, chips, next_event_id=3) == 3


def test_events_at_or_after_next_are_ignored():
    events = [_ev(1, 0), _ev(2, 3)]  # GW2 row present but next_event_id=2 -> ignore it
    assert derive_free_transfers(events, [], next_event_id=2) == 2


def test_clamp_ft():
    assert clamp_ft(0) == 1
    assert clamp_ft(3) == 3
    assert clamp_ft(9) == 5
    assert clamp_ft(None) is None
    assert clamp_ft("2") == 2
