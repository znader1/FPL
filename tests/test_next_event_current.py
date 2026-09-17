"""`current_event_id` on the next-event summary."""
import pandas as pd

from api import main as api_main


def _bootstrap(current=None, nxt=None):
    events = [
        {
            "id": i,
            "is_current": i == current,
            "is_next": i == nxt,
            "finished": current is not None and i < current,
            "deadline_time": f"2026-08-{min(28, 20 + i):02d}T17:30:00Z",
        }
        for i in range(1, 6)
    ]
    return {"events": events}


def _summary(current, nxt):
    return api_main.build_next_event_summary(
        bootstrap=_bootstrap(current=current, nxt=nxt), fixtures=pd.DataFrame())


def test_reports_the_gameweek_currently_in_progress():
    out = _summary(current=2, nxt=3)
    assert out["current_event_id"] == 2
    assert out["event_id"] == 3


def test_current_is_none_before_the_first_deadline():
    # Pre-season: GW1 is next, nothing is live yet. `event_id - 1` would say GW0.
    out = _summary(current=None, nxt=1)
    assert out["current_event_id"] is None
    assert out["event_id"] == 1


def test_current_is_none_between_a_finished_gw_and_the_next_flag():
    """
    The window `event_id - 1` gets wrong: nothing current, nothing next yet.
    Deriving from `event_id` here would mark a finished gameweek as live.
    """
    out = _summary(current=None, nxt=None)
    assert out["current_event_id"] is None


def test_no_events_returns_a_null_current():
    out = api_main.build_next_event_summary(bootstrap={"events": []}, fixtures=pd.DataFrame())
    assert out["current_event_id"] is None
    assert out["event_id"] is None
