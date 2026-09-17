"""Market-implied team goal expectations from bookmaker odds.

The betting market is the sharpest public predictor of team goals — it prices
team news, rotation and motivation that decayed xG can't see. This module
turns a fixture's 1X2 + over/under odds into per-team expected goals:

1. de-vig each market (normalise implied probabilities to 1),
2. invert the totals market: find total lambda with
   P(Poisson(lam) > line) = p_over,
3. split the total by supremacy: find (lam_home, lam_away) summing to the
   total whose independent-Poisson P(home wins) matches the de-vigged 1X2.

Everything is pure and fail-soft: malformed input returns None.
"""
from __future__ import annotations
import math

_MAX_GOALS = 12  # truncation for Poisson win-prob sums


def devig(decimal_odds):
    """Normalise decimal odds to a probability vector summing to 1."""
    inv = [1.0 / float(o) for o in decimal_odds]
    total = sum(inv)
    return [p / total for p in inv]


def _poisson_pmf(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _p_over(lam, line):
    """P(N > line) for half-lines (2.5 → P(N >= 3))."""
    need = int(math.floor(line)) + 1
    return 1.0 - sum(_poisson_pmf(lam, k) for k in range(need))


def implied_total_lambda(p_over, line=2.5, lo=0.2, hi=8.0, tol=1e-6):
    """Invert P(Poisson(lam) > line) = p_over by bisection."""
    p_over = min(max(float(p_over), 1e-6), 1.0 - 1e-6)
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if _p_over(mid, line) < p_over:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2.0


def _p_home_win(lam_h, lam_a):
    """P(H > A) for independent Poissons, truncated at _MAX_GOALS."""
    pa = [_poisson_pmf(lam_a, k) for k in range(_MAX_GOALS + 1)]
    cum_a = []
    run = 0.0
    for k in range(_MAX_GOALS + 1):
        cum_a.append(run)  # P(A < k)
        run += pa[k]
    return sum(_poisson_pmf(lam_h, k) * cum_a[k] for k in range(1, _MAX_GOALS + 1))


def split_supremacy(total_lam, p_home, p_away, tol=1e-5):
    """Split total goals into (lam_home, lam_away) matching the market's
    home-win probability. Bisect the difference d = lam_home - lam_away;
    P(H>A) is monotonic in d at fixed total."""
    total_lam = float(total_lam)
    lo, hi = -total_lam + 1e-6, total_lam - 1e-6
    target = float(p_home)
    for _ in range(60):
        d = (lo + hi) / 2.0
        lh, la = (total_lam + d) / 2.0, (total_lam - d) / 2.0
        if _p_home_win(lh, la) < target:
            lo = d
        else:
            hi = d
        if hi - lo < tol:
            break
    d = (lo + hi) / 2.0
    return (total_lam + d) / 2.0, (total_lam - d) / 2.0


def implied_fixture_lambdas(fixture_odds):
    """Full pipeline for one fixture dict:
        {home_team, away_team, h2h: [home, draw, away] decimal odds,
         totals: {line, over, under}}
    Returns {home_team, away_team, lam_home, lam_away, total_lam,
             p_home, p_draw, p_away} or None when a market is missing/bad.
    """
    try:
        h2h = fixture_odds.get("h2h")
        totals = fixture_odds.get("totals") or {}
        if not h2h or len(h2h) != 3:
            return None
        line = totals.get("line")
        over, under = totals.get("over"), totals.get("under")
        if line is None or over is None or under is None:
            return None

        p_home, p_draw, p_away = devig(h2h)
        p_over = devig([over, under])[0]
        total_lam = implied_total_lambda(p_over, line=float(line))
        lam_home, lam_away = split_supremacy(total_lam, p_home, p_away)
        return {
            "home_team": fixture_odds.get("home_team"),
            "away_team": fixture_odds.get("away_team"),
            "lam_home": lam_home,
            "lam_away": lam_away,
            "total_lam": lam_home + lam_away,
            "p_home": p_home,
            "p_draw": p_draw,
            "p_away": p_away,
        }
    except Exception:
        return None
