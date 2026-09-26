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


def test_flag_off_plan_ignores_play_prob(monkeypatch):
    with_col = _injury_hit_squad()
    without_col = with_col.drop(columns=["play_prob"])
    a = json.dumps(_plan(with_col), sort_keys=True, default=str)
    b = json.dumps(_plan(without_col), sort_keys=True, default=str)
    assert a == b
