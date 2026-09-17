"""
Points distribution for a single player-gameweek.

``output_model`` produces a mean: 2.3, 3.1. No player ever scores 2.3, and the
mean hides the decision a manager is actually making -- whether a pick is a safe
two points or a coin-flip between one and thirteen.

This module convolves the components ``output_model`` already computes into a
probability mass function over whole points, so the UI can show the most likely
score, the odds of a return, and the odds of a haul.

Scope: the DISCRETE scoring events only -- appearance, goals, assists, clean
sheets and defensive contribution. Bonus, goals-conceded and saves stay
continuous expectations and are added back by the caller:

    pmf_mean + ep_bonus + ep_conceded + ep_saves == exp_points

Bonus is deliberately excluded rather than approximated: it correlates with
goals and assists, so folding it in as an independent term would overstate the
tail exactly where the tail matters most.

Ranking stays on the mean. Expectation is the right objective over a season;
this distribution is for display and risk.
"""

import numpy as np

try:
    from . import config
except Exception:  # pragma: no cover
    import config  # type: ignore


# Points ceiling for the support. A single player-gameweek beyond this is far
# outside anything the component model can produce.
MAX_POINTS = 30


def _blank(max_points):
    pmf = np.zeros(max_points + 1, dtype=float)
    pmf[0] = 1.0
    return pmf


def _convolve(pmf, other, max_points):
    """Convolve two distributions and fold any overflow into the top bucket."""
    out = np.convolve(pmf, other)
    if out.size > max_points + 1:
        head = out[: max_points + 1].copy()
        head[max_points] += out[max_points + 1:].sum()
        out = head
    return out


def _shift(prob_by_count, points_each, max_points):
    """Spread a count distribution across the points axis at `points_each` apiece."""
    pmf = np.zeros(max_points + 1, dtype=float)
    step = int(points_each)
    for count, prob in enumerate(prob_by_count):
        if prob <= 0.0:
            continue
        idx = min(max_points, count * step)
        pmf[idx] += prob
    return pmf


def _poisson_counts(lam, max_count):
    """Poisson pmf over 0..max_count, with the remaining tail folded into the top."""
    lam = max(0.0, float(lam))
    counts = np.arange(max_count + 1)
    logs = -lam + counts * np.log(lam) if lam > 0 else None
    if logs is None:
        pmf = np.zeros(max_count + 1, dtype=float)
        pmf[0] = 1.0
        return pmf
    # log factorial via cumulative sum keeps this exact for the small counts used.
    log_fact = np.concatenate(([0.0], np.cumsum(np.log(counts[1:]))))
    pmf = np.exp(logs - log_fact)
    pmf[-1] += max(0.0, 1.0 - pmf.sum())
    return pmf


def _appearance_pmf(prob_appear, prob_60, max_points):
    """
    1 point for appearing, a second for reaching 60 minutes.

    `prob_60` above `prob_appear` is nonsense but upstream minutes models can
    emit it; clamp rather than produce negative mass.
    """
    p_appear = float(np.clip(prob_appear, 0.0, 1.0))
    p_60 = float(np.clip(prob_60, 0.0, p_appear))
    pmf = np.zeros(max_points + 1, dtype=float)
    pmf[0] = 1.0 - p_appear
    pmf[1] = p_appear - p_60
    pmf[2] = p_60
    return pmf


def _bernoulli_pmf(prob, points, max_points):
    p = float(np.clip(prob, 0.0, 1.0))
    pmf = np.zeros(max_points + 1, dtype=float)
    idx = min(max_points, max(0, int(points)))
    pmf[0] += 1.0 - p
    pmf[idx] += p
    return pmf


def _clean_sheet_pmf(exp_clean_sheets, n_fixtures, cs_points, max_points):
    """
    Clean sheets as `n_fixtures` independent Bernoullis of the per-fixture mean.

    A double gameweek can bank two clean sheets, so this is a count rather than a
    single Bernoulli. Splitting the expected count evenly keeps the mean exact;
    the shape is an approximation, since the two fixtures are not equally hard.
    """
    n = max(1, int(n_fixtures or 1))
    total = max(0.0, float(exp_clean_sheets))
    if total <= 0.0 or int(cs_points) == 0:
        return _blank(max_points)
    per_fixture = min(1.0, total / n)
    pmf = _blank(max_points)
    for _ in range(n):
        pmf = _convolve(pmf, _bernoulli_pmf(per_fixture, cs_points, max_points), max_points)
    return pmf


def player_points_pmf(pos, prob_appear, prob_60, exp_goals, exp_assists,
                      exp_clean_sheets=0.0, n_fixtures=1, p_dc=0.0,
                      max_points=MAX_POINTS):
    """
    Probability of each whole-point outcome for one player-gameweek.

    Returns an array indexed by points, summing to 1.
    """
    goal_pts = int(getattr(config, "OUTPUT_GOAL_POINTS", {}).get(pos, 4))
    assist_pts = int(getattr(config, "OUTPUT_ASSIST_POINTS", 3.0))
    cs_pts = int(getattr(config, "OUTPUT_CS_POINTS", {}).get(pos, 0))
    dc_pts = int(getattr(config, "OUTPUT_DC_POINTS", 2.0))

    # Enough counts to cover the clamped expected goals/assists tail.
    max_count = max(1, int(max_points // max(1, goal_pts)) + 2)

    pmf = _appearance_pmf(prob_appear, prob_60, max_points)
    pmf = _convolve(pmf, _shift(_poisson_counts(exp_goals, max_count), goal_pts, max_points), max_points)
    pmf = _convolve(pmf, _shift(_poisson_counts(exp_assists, max_count), assist_pts, max_points), max_points)
    pmf = _convolve(pmf, _clean_sheet_pmf(exp_clean_sheets, n_fixtures, cs_pts, max_points), max_points)
    pmf = _convolve(pmf, _bernoulli_pmf(p_dc, dc_pts, max_points), max_points)

    total = pmf.sum()
    return pmf / total if total > 0 else pmf


def discrete_expected_points(pos, prob_appear, prob_60, exp_goals, exp_assists,
                             exp_clean_sheets=0.0, n_fixtures=1, p_dc=0.0,
                             max_points=MAX_POINTS):
    """
    Mean of the discrete components, computed directly from the inputs.

    Mirrors the corresponding terms in ``output_model.expected_points``. Used to
    assert the distribution reproduces the model rather than drifting from it.
    """
    goal_pts = int(getattr(config, "OUTPUT_GOAL_POINTS", {}).get(pos, 4))
    assist_pts = float(getattr(config, "OUTPUT_ASSIST_POINTS", 3.0))
    cs_pts = float(getattr(config, "OUTPUT_CS_POINTS", {}).get(pos, 0))
    dc_pts = float(getattr(config, "OUTPUT_DC_POINTS", 2.0))

    p_appear = float(np.clip(prob_appear, 0.0, 1.0))
    p_60 = float(np.clip(prob_60, 0.0, p_appear))
    return (p_appear + p_60
            + max(0.0, float(exp_goals)) * goal_pts
            + max(0.0, float(exp_assists)) * assist_pts
            + max(0.0, float(exp_clean_sheets)) * cs_pts
            + float(np.clip(p_dc, 0.0, 1.0)) * dc_pts)


def summarize(pmf, return_at=6, haul_at=10, band=0.80):
    """
    The handful of numbers worth putting on a player card.

    `modal_points` is the single most likely score -- the answer to "what will
    this player actually get", which the mean can never give.
    """
    pmf = np.asarray(pmf, dtype=float)
    points = np.arange(pmf.size)
    cdf = np.cumsum(pmf)

    tail = (1.0 - band) / 2.0
    low = int(np.searchsorted(cdf, tail))
    high = int(np.searchsorted(cdf, 1.0 - tail))
    high = min(high, pmf.size - 1)

    return {
        "modal_points": int(np.argmax(pmf)),
        "mean_points": float((points * pmf).sum()),
        f"p_return_{return_at}": float(pmf[return_at:].sum()) if return_at < pmf.size else 0.0,
        f"p_haul_{haul_at}": float(pmf[haul_at:].sum()) if haul_at < pmf.size else 0.0,
        "p80_low": low,
        "p80_high": high,
    }
