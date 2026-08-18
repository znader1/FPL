from api.main import _is_pre_first_deadline


def _boot(current=None, nxt=None):
    events = []
    for i in range(1, 39):
        events.append({
            "id": i,
            "is_current": i == current,
            "is_next": i == nxt,
        })
    return {"events": events}


def test_true_before_first_deadline():
    # Pre-season: GW1 is next, nothing current.
    assert _is_pre_first_deadline(_boot(current=None, nxt=1)) is True


def test_false_once_a_gameweek_is_current():
    # GW1 deadline passed -> GW1 current, GW2 next: unlimited-transfer window is over.
    assert _is_pre_first_deadline(_boot(current=1, nxt=2)) is False
    assert _is_pre_first_deadline(_boot(current=5, nxt=6)) is False


def test_false_at_season_end():
    # Final GW current, no next.
    assert _is_pre_first_deadline(_boot(current=38, nxt=None)) is False


def test_false_when_no_events():
    assert _is_pre_first_deadline({"events": []}) is False
