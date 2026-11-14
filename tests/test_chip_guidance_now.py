"""When the best wildcard week IS the deadline week, the guidance must say so:
"re-check later" is wrong advice for a chip whose window is this GW."""
from src import chip_advisor


def _hold(event_id, current_gw):
    return chip_advisor._chip_guidance(
        "wildcard", status="hold", event_id=event_id, ev_gain=7.5, bar=120.0,
        distribution={"p_beats_bar": 0.02}, horizon=6, half=1,
        transfer_plan_net_gain=3.0, current_gw=current_gw,
    )


def test_best_week_is_now_says_so():
    text = _hold(event_id=8, current_gw=8)
    assert text.startswith("Not this week. A wildcard now gains +7.5 pts")
    assert "120" in text and "Keep it for" in text
    assert "best" not in text.lower().split("keep it for")[0]
    assert "re-check" not in text.lower()


def test_best_week_later_keeps_hold_copy():
    text = _hold(event_id=12, current_gw=8)
    assert text.startswith("Hold for now. GW12")


def test_now_copy_never_says_free_transfers_cover_the_gain():
    # The gain is already net of the transfer plan; saying FTs cover it contradicts it.
    text = chip_advisor._chip_guidance(
        "wildcard", status="hold", event_id=11, ev_gain=34.7, bar=40.0,
        distribution=None, horizon=5, half=1, current_gw=11, window_gws=[11, 12, 13, 14, 15],
    )
    assert "cover" not in text.lower()
    assert "beyond what your planned transfers already get" in text

