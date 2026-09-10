"""Joint return odds for same-team attacker stacks in a draft XI.

A mean-xPts sum is blind to correlation: three attackers from one club share
one team performance, so "all return" needs the TEAM to score multiple goals
and "all blank" happens in a single flat game. This module makes that shape
visible.

Model (deliberately simple, annotation-grade):
- Team goals G ~ Poisson(lam), lam = the team's expected xG vs this GW's
  opponent(s) (DGW = summed), from the fixture-difficulty ratings.
- Each goal carries ~CHIP_STACK_SLOTS_PER_GOAL return slots (scorer +
  assister).
- Player i's chance of taking any one slot is their share of the stacked
  trio's xGI (equal shares when xGI data is missing).
- P(i returns | G=g) = 1 - (1 - share_i)^(slots*g); players treated as
  conditionally independent given G — an approximation that slightly fattens
  both joint tails, acceptable for an annotation.
"""
from __future__ import annotations
import math

from src import config

_ATTACKER_POS = {"MID", "FWD"}


def _poisson_pmf(lam: float, g: int) -> float:
    return math.exp(-lam) * lam ** g / math.factorial(g)


def stack_odds_for_xi(
    xi_rows,
    lambda_by_team: dict[int, float],
    xgi_by_player: dict[int, float],
    min_stack: int | None = None,
    slots_per_goal: float | None = None,
    max_goals: int = 10,
) -> list[dict]:
    """Odds rows for every same-team attacker stack in the XI.

    xi_rows: iterable of dicts/rows with player_id, web_name, pos, team.
    lambda_by_team: team id -> expected team goals this GW (DGW summed).
    Teams without a lambda are skipped (no fixture data — no claim).
    Returns [{team, n, players, lam, p_all_return, p_all_blank}].
    """
    min_stack = int(min_stack or getattr(config, "CHIP_STACK_ODDS_MIN", 2))
    slots = float(slots_per_goal or getattr(config, "CHIP_STACK_SLOTS_PER_GOAL", 2.0))

    by_team: dict[int, list[dict]] = {}
    for r in xi_rows:
        if r.get("pos") not in _ATTACKER_POS:
            continue
        try:
            t = int(r.get("team"))
        except (TypeError, ValueError):
            continue
        by_team.setdefault(t, []).append(r)

    out = []
    for team, players in sorted(by_team.items()):
        if len(players) < min_stack:
            continue
        lam = lambda_by_team.get(team)
        if lam is None or not math.isfinite(float(lam)) or float(lam) <= 0:
            continue
        lam = float(lam)

        xgis = []
        for p in players:
            try:
                xgis.append(max(0.0, float(xgi_by_player.get(int(p.get("player_id")), 0.0) or 0.0)))
            except (TypeError, ValueError):
                xgis.append(0.0)
        total = sum(xgis)
        if total <= 0:
            shares = [1.0 / len(players)] * len(players)
        else:
            shares = [x / total for x in xgis]

        p_all_return = 0.0
        p_all_blank = 0.0
        for g in range(0, max_goals + 1):
            pg = _poisson_pmf(lam, g)
            ret = 1.0
            blank = 1.0
            for s in shares:
                miss = (1.0 - s) ** (slots * g)
                ret *= 1.0 - miss
                blank *= miss
            p_all_return += pg * ret
            p_all_blank += pg * blank

        out.append({
            "team": team,
            "n": len(players),
            "players": [str(p.get("web_name", p.get("player_id"))) for p in players],
            "lam": round(lam, 2),
            "p_all_return": round(p_all_return, 3),
            "p_all_blank": round(p_all_blank, 3),
        })
    return out
