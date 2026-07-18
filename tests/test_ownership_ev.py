from src import ownership_ev


def _meta(pid, xpts, own_pct, ep_next=None, league_own=None):
    m = {"position_id": pid, "model_xpts_horizon": xpts, "selected_by_percent": own_pct}
    if ep_next is not None:
        m["ep_next"] = ep_next
    if league_own is not None:
        m["league_ownership"] = league_own
    return m


def test_xpts_of_fallback_chain():
    assert ownership_ev.xpts_of({"model_xpts_horizon": 12.0}) == 12.0
    assert ownership_ev.xpts_of({"model_xpts_horizon": None, "ep_next": "3.5"}) == 3.5
    assert ownership_ev.xpts_of({"model_xpts_horizon": None, "ep_next": None}) == 0.0


def test_position_template_is_global_ownership_weighted():
    # Two MIDs: high-owned 10pt, low-owned 2pt. Weighted avg tilts toward the high-owned.
    elements = {
        1: _meta(3, 10.0, "50.0"),
        2: _meta(3, 2.0, "5.0"),
        3: _meta(4, 8.0, "20.0"),
    }
    t = ownership_ev.compute_position_templates(elements)
    # MID: (50*10 + 5*2)/(55) = 510/55 = 9.2727...
    assert abs(t[3] - (510.0 / 55.0)) < 1e-6
    assert abs(t[4] - 8.0) < 1e-6


def test_position_template_zero_ownership_falls_back_to_mean():
    elements = {1: _meta(2, 4.0, "0"), 2: _meta(2, 6.0, "0")}
    t = ownership_ev.compute_position_templates(elements)
    assert abs(t[2] - 5.0) < 1e-6


def test_differential_ev_formula():
    # above template, low ownership -> high EV
    assert abs(ownership_ev.differential_ev(10.0, 6.0, 0.0) - 4.0) < 1e-9
    # owned by whole league -> ~0 regardless of xpts
    assert abs(ownership_ev.differential_ev(10.0, 6.0, 1.0) - 0.0) < 1e-9
    # below template -> negative
    assert ownership_ev.differential_ev(3.0, 6.0, 0.0) < 0
    # ownership clipped: >1 treated as 1
    assert abs(ownership_ev.differential_ev(10.0, 6.0, 1.5) - 0.0) < 1e-9


def test_annotate_candidates_adds_ev_and_template():
    templates = {3: 6.0}
    cands = [{"id": 1, "position_id": 3, "model_xpts_horizon": 10.0, "league_ownership": 0.25}]
    out = ownership_ev.annotate_candidates(cands, templates)
    assert out[0]["template_xpts"] == 6.0
    assert abs(out[0]["differential_ev"] - (10.0 - 6.0) * 0.75) < 1e-9
    # original list not mutated
    assert "differential_ev" not in cands[0]
