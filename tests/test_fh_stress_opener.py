"""Roadmap 2.1 — the Free Hit squad-stress opener ships off, and its three fixes.

Off (CHIP_PLAN_FH_MIN_STRESS = 0) must be the pre-2.1 chip plan exactly: the
stress code is never reached and the squad's play_prob column changes nothing.
"""
import json

import pytest

from src import chip_advisor, config
from src.chip_advisor import build_chip_plan
from tests.test_chip_advisor import _market_for, _squad_15_single_team


def _plan(squad, difficulty=3.6):
    gw_projections = {g: _market_for(squad, gw_xpts=2.0) for g in range(5, 9)}
    return build_chip_plan(
        squad=squad, current_gw=5, gw_projections=gw_projections,
        chips_played=[], itb_m=0.0, horizon_gws=4,
        team_difficulty_by_gw={g: {"Arsenal": difficulty} for g in range(5, 9)},
    )


def _injury_hit_squad():
    squad = _squad_15_single_team(team="Arsenal")
    squad["price_m"] = 5.0
    squad["play_prob"] = 1.0
    squad.loc[squad.index[:5], "play_prob"] = 0.0
    squad["is_starter"] = [True] * 11 + [False] * 4
    return squad


# --- flag off == pre-2.1 behaviour ------------------------------------------

def test_flag_defaults_off():
    assert config.CHIP_PLAN_FH_MIN_STRESS == 0


def test_flag_off_never_reaches_the_stress_code(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("stress code reached while the opener is off")

    monkeypatch.setattr(chip_advisor, "fh_squad_stress", boom)
    monkeypatch.setattr(chip_advisor, "fh_best_stress_row", boom)
    plan = _plan(_injury_hit_squad(), difficulty=4.8)
    assert all("stress" not in row for row in plan["outlook"])


def test_flag_off_plan_ignores_the_new_squad_columns(monkeypatch):
    with_col = _injury_hit_squad()
    without_col = with_col.drop(columns=["play_prob", "is_starter"])
    a = json.dumps(_plan(with_col), sort_keys=True, default=str)
    b = json.dumps(_plan(without_col), sort_keys=True, default=str)
    assert a == b


# --- Fix 1: stress counts the manager's starting XI, not the structural bench ---

def _squad_with_fodder_bench(fixture_count=True):
    """All fit; the 4 bench slots (positions 12-15) are fodder who never start.
    ``fixture_count`` is for calling fh_squad_stress directly; in a chip plan
    the market supplies it."""
    squad = _squad_15_single_team(team="Arsenal")
    squad["price_m"] = 5.0
    squad["is_starter"] = [True] * 11 + [False] * 4
    squad["play_prob"] = [1.0] * 11 + [0.25] * 4   # benched 3 of 3 -> 0.25
    if fixture_count:
        squad["fixture_count"] = 1
    return squad


def test_fodder_bench_adds_no_stress():
    stress = chip_advisor.fh_squad_stress(_squad_with_fodder_bench(), {"Arsenal": 3.0})
    assert stress["total"] == 0.0
    assert stress["n_unavailable"] == 0
    assert stress["scope"] == 11


def test_fodder_bench_does_not_fire_free_hit(monkeypatch):
    monkeypatch.setattr(config, "CHIP_PLAN_FH_MIN_STRESS", 3.0)
    plan = _plan(_squad_with_fodder_bench(fixture_count=False), difficulty=3.0)
    assert not any(r["chip"] == "free_hit" for r in plan["recommendations"])


def test_injured_starter_still_counts():
    squad = _squad_with_fodder_bench()
    squad.loc[squad.index[0], "play_prob"] = 0.0          # a starter is out
    stress = chip_advisor.fh_squad_stress(squad, {"Arsenal": 3.0})
    assert stress["total"] == pytest.approx(1.0)
    assert stress["unavailable_names"] == ["P1"]


def test_without_positions_all_fifteen_count():
    squad = _squad_with_fodder_bench().drop(columns=["is_starter"])
    stress = chip_advisor.fh_squad_stress(squad, {"Arsenal": 3.0})
    assert stress["total"] == pytest.approx(3.0)           # 4 x 0.75, the old reading
    assert stress["scope"] == 15


# --- Fix 2: a returning player's injured weeks don't read as "benched" --------

def test_recent_news_skips_the_benching_signal():
    p = chip_advisor.start_prob_from_recent_starts(
        [0.0, 0.0], [3, 3], news_recent=[True, False])
    assert p.tolist() == [1.0, 0.25]          # back from injury vs benched all along


def test_news_recent_absent_keeps_the_old_signal():
    assert chip_advisor.start_prob_from_recent_starts([0.0], [3]).tolist() == [0.25]


def test_news_changed_since():
    since = "2026-08-29T17:30:00Z"
    news = ["2026-09-04T14:00:08Z", "2026-07-23T12:01:23Z", None, "", "garbage"]
    assert chip_advisor.news_changed_since(news, since).tolist() == [True, False, False, False, False]


def test_recent_window_start_deadline_uses_the_projection_window():
    events = [{"id": g, "deadline_time": f"2026-08-{10 + g:02d}T17:30:00Z"} for g in range(1, 8)]
    window = config.PROJ_PLAYER_RECENT_GW_WINDOW
    got = chip_advisor.recent_window_start_deadline(events, current_gw=7)
    assert got == events[max(1, 7 - window) - 1]["deadline_time"]
    assert chip_advisor.recent_window_start_deadline(events, current_gw=2) == events[0]["deadline_time"]
    assert chip_advisor.recent_window_start_deadline([], current_gw=7) is None
