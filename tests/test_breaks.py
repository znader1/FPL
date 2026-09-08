from src.breaks import international_break_gws


def _events(deadlines):
    return [{"id": i + 1, "deadline_time": d} for i, d in enumerate(deadlines)]


def test_normal_weekly_cadence_no_breaks():
    ev = _events([
        "2026-08-15T17:30:00Z", "2026-08-22T17:30:00Z", "2026-08-29T17:30:00Z",
    ])
    assert international_break_gws(ev) == {}


def test_fourteen_day_gap_flags_post_break_gw():
    ev = _events([
        "2026-08-29T17:30:00Z", "2026-09-12T17:30:00Z", "2026-09-19T17:30:00Z",
    ])
    out = international_break_gws(ev)
    assert set(out) == {2}
    assert out[2]["prev_event"] == 1
    assert out[2]["gap_days"] == 14.0


def test_gap_days_parameter_overrides_config():
    ev = _events(["2026-08-29T17:30:00Z", "2026-09-06T17:30:00Z"])  # 8-day gap
    assert set(international_break_gws(ev, gap_days=7.5)) == {2}
    assert international_break_gws(ev, gap_days=10.0) == {}


def test_malformed_deadlines_yield_empty_map():
    ev = [{"id": 1, "deadline_time": None}, {"id": 2, "deadline_time": "not-a-date"},
          {"id": 3}]
    assert international_break_gws(ev) == {}


def test_events_sorted_by_id_not_input_order():
    ev = [
        {"id": 2, "deadline_time": "2026-09-12T17:30:00Z"},
        {"id": 1, "deadline_time": "2026-08-29T17:30:00Z"},
    ]
    assert set(international_break_gws(ev)) == {2}
