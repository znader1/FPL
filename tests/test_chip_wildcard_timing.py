"""Wildcard timed through expiry (spec 2026-11-26-wildcard-timing-through-expiry)."""
import pandas as pd
import pytest

from src import config
from src.chip_advisor import build_chip_plan, pick_wildcard_week, score_wildcard
from tests.test_chip_advisor import _squad_15

FIRST_HALF_OTHERS = [{"name": c, "event": 1} for c in ("freehit", "bboost", "3xc")]


def _market(gws, star_xpts=None):
    """Own squad at 2 xPts; a star squad at 2 + 1/11 a player per GW (or per-GW values)."""
    own = _squad_15(xpts=2.0)
    proj = {}
    for g in gws:
        stars = _squad_15(prefix="star", xpts=(star_xpts or {}).get(g, 2.0 + 1.0 / 11))
        stars["player_id"] = stars["player_id"] + 100
        proj[g] = pd.concat([own, stars], ignore_index=True)
    return own[["player_id", "name", "pos", "team", "price_m"]], proj


STARS = set(range(101, 116))


def test_end_gw_scores_through_expiry():
    squad, proj = _market([1, 2, 3])
    wc = {g: STARS for g in (1, 2, 3)}
    full = score_wildcard(squad, proj, [1, 2], horizon=2, wc_squads=wc, end_gw=3)
    by_gw = {r.gw: r for r in full}
    assert by_gw[1].expected_value == pytest.approx(3.0)
    assert by_gw[1].window_gws == [1, 3]
    assert by_gw[2].expected_value == pytest.approx(2.0)
    fixed = score_wildcard(squad, proj, [1], horizon=2, wc_squads=wc)
    assert fixed[0].expected_value == pytest.approx(2.0)


OWNER = {12: 17.4, 13: 10.2, 14: 8.9, 15: 10.2, 16: 9.6, 17: 7.9, 18: 5.1, 19: 2.0}
ORDINARY = {12: 0.9, 13: 0.4, 14: 2.1, 15: 6.3, 16: 6.3, 17: 5.2, 18: 2.8, 19: 0.6}


def test_owner_shape_plays_now():
    p = pick_wildcard_week(OWNER, now_gw=12, margin=3.0)
    assert p["event_id"] == 12 and p["play_now"] is True
    assert p["next_best_gw"] == 13 and p["next_best_gain"] == pytest.approx(10.2)
    assert p["bar"] == pytest.approx(7.2)
    assert p["now_gain"] == pytest.approx(17.4)


def test_ordinary_shape_waits_for_best_later_week():
    p = pick_wildcard_week(ORDINARY, now_gw=12, margin=3.0)
    assert p["event_id"] == 15 and p["play_now"] is False


def test_slightly_better_later_week_is_not_worth_waiting_for():
    p = pick_wildcard_week({12: 10.0, 13: 12.0}, now_gw=12, margin=3.0)
    assert p["event_id"] == 12 and p["play_now"] is True
    p = pick_wildcard_week({12: 10.0, 13: 13.5}, now_gw=12, margin=3.0)
    assert p["event_id"] == 13 and p["play_now"] is False


@pytest.mark.parametrize("curve,expected", [
    (ORDINARY, 15),
    (OWNER, 12),
    ({g: float(20 - g) for g in range(12, 20)}, 12),  # flat 1 pt a GW: decays by construction
])
def test_rolled_forward_the_plan_plays_the_best_week_not_the_expiry_week(curve, expected):
    for gw in range(12, 20):
        remaining = {g: v for g, v in curve.items() if g >= gw}
        if pick_wildcard_week(remaining, now_gw=gw, margin=3.0, end_gw=19)["play_now"]:
            assert gw == expected
            return
    pytest.fail("never played")


def test_expiry_week_plays_any_positive_gain():
    p = pick_wildcard_week({19: 0.6}, now_gw=19, margin=3.0)
    assert p["event_id"] == 19 and p["play_now"] is True
    assert p["bar"] == 0.0 and p["next_best_gw"] is None


def test_small_gain_with_nothing_later_plays_now():
    p = pick_wildcard_week({12: 2.0}, now_gw=12, margin=3.0, end_gw=19)
    assert p["event_id"] == 12 and p["play_now"] is True
    assert p["next_best_gain"] == 0.0 and p["next_best_gw"] is None and p["bar"] == 0.0


def test_missing_now_week_plans_later():
    p = pick_wildcard_week({14: 5.0}, now_gw=12, margin=3.0)
    assert p["event_id"] == 14 and p["play_now"] is False and p["now_gain"] == 0.0


def test_nothing_positive():
    p = pick_wildcard_week({}, now_gw=12, margin=3.0)
    assert p["event_id"] is None and p["play_now"] is False


def _wc_outlook(plan):
    return next(o for o in plan["outlook"] if o["chip"] == "wildcard")


def test_plan_times_wildcard_through_expiry_when_in_view():
    gws = list(range(12, 20))
    squad, proj = _market(gws)
    plan = build_chip_plan(squad=squad, current_gw=12, gw_projections=proj,
                           chips_played=FIRST_HALF_OTHERS, horizon_gws=8,
                           wc_squads={g: STARS for g in gws})
    row = _wc_outlook(plan)
    # 1 pt a GW: now gets 8 through GW19, GW13 gets 7 — no reason to wait.
    assert row["timing"]["end_gw"] == 19
    assert row["timing"]["now_gain"] == pytest.approx(8.0)
    assert row["timing"]["next_best_gw"] == 13
    assert row["status"] == "play" and row["event_id"] == 12
    assert plan["nudge"]["chip"] == "wildcard"


def test_plan_waits_for_a_clearly_better_later_week():
    gws = list(range(12, 20))
    # Stars level with the squad until GW15, then +6 a GW for GW15-19: playing in
    # GW15 gets the whole swing; playing now gets the same 30 — so it plays now.
    # Make the early weeks negative for the stars instead: now loses 3 a GW first.
    squad, proj = _market(gws, star_xpts={g: (2.0 - 3.0 / 11 if g < 15 else 2.0 + 6.0 / 11) for g in gws})
    plan = build_chip_plan(squad=squad, current_gw=12, gw_projections=proj,
                           chips_played=FIRST_HALF_OTHERS, horizon_gws=8,
                           wc_squads={g: STARS for g in gws})
    row = _wc_outlook(plan)
    assert row["event_id"] == 15 and row["status"] == "play"
    assert plan["nudge"] is None
    assert row["guidance"].startswith("Hold this week. GW15")


def test_plan_plays_now_when_now_beats_later_by_margin():
    gws = list(range(12, 20))
    # Stars far ahead in GW12-14 (+11 a GW), +1 a GW afterwards: 33 + 5.
    squad, proj = _market(gws, star_xpts={12: 3.0, 13: 3.0, 14: 3.0})
    plan = build_chip_plan(squad=squad, current_gw=12, gw_projections=proj,
                           chips_played=FIRST_HALF_OTHERS, horizon_gws=8,
                           wc_squads={g: STARS for g in gws})
    row = _wc_outlook(plan)
    assert row["status"] == "play" and row["event_id"] == 12
    assert row["timing"]["now_gain"] == pytest.approx(38.0)
    assert plan["nudge"]["chip"] == "wildcard"
    assert "GW19" in row["guidance"]


def test_early_season_keeps_the_bar_rule(monkeypatch):
    gws = list(range(5, 13))
    squad, proj = _market(gws)
    plan = build_chip_plan(squad=squad, current_gw=5, gw_projections=proj,
                           chips_played=FIRST_HALF_OTHERS, horizon_gws=8,
                           wc_squads={g: STARS for g in gws})
    row = _wc_outlook(plan)
    assert "timing" not in row
    assert row["bar"] == pytest.approx(config.CHIP_PLAN_MIN_EV["wildcard"]) == pytest.approx(25.0)
    assert row["status"] == "hold"


def test_second_half_enters_timing_mode_at_gw31():
    gws = list(range(31, 39))
    squad, proj = _market(gws)
    played = [{"name": c, "event": 1} for c in ("wildcard", "freehit", "bboost", "3xc")] + \
             [{"name": c, "event": 21} for c in ("freehit", "bboost", "3xc")]
    plan = build_chip_plan(squad=squad, current_gw=31, gw_projections=proj,
                           chips_played=played, horizon_gws=8,
                           wc_squads={g: STARS for g in gws})
    assert _wc_outlook(plan)["timing"]["end_gw"] == 38
