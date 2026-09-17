"""Per-player, per-gameweek points distributions for the chip planner.

The chip EV is a mean and stays a mean (expectation is the right objective).
But "Triple Captain in GW12 projects +9.1" hides the decision a manager is
really weighing — is that a safe 7 or a coin-flip between 2 and 18? This
module gives every model-zone chip candidate the shape behind its number:

* P(return)  — the captain scores at least `RETURN_AT` (TC only: the
               thresholds are per-player and say nothing about a bench-4 sum)
* P(haul)    — at least `HAUL_AT`
* P(blank)   — at most `BLANK_AT`
* P(beats bar) — the chip's extra points clear its play/hold threshold
* the 80% band and the single most likely score

Mechanics: the same event convolution the player cards use
(`points_distribution.player_points_pmf`) fed with a lightweight per-player
prior (per-90 xG/xA, start rate, availability from the bootstrap) and the
GW's fixture context (fixture count, difficulty). The goal/assist/clean-sheet
lambdas are then scaled so the pmf's mean matches the engine's blended xPts
for that player-GW (minus the continuous share — bonus, saves, conceded —
the pmf deliberately excludes), so the shape and the EV never disagree.

TC extra points = the captain's own score (x3 vs x2), so the TC gain
distribution IS the captain's pmf. BB extra points = the bench-4 sum, so the
BB gain distribution is the convolution of the four bench pmfs (independent —
same-team correlation is ignored, which slightly understates the tails).
FH/WC gains come from optimizer-built dream squads and have no distribution.

Axis note: `points_distribution.MAX_POINTS` (30) is the ceiling for ONE
player-gameweek. A double-gameweek captain and a bench-4 sum both live well
above it, so every pmf here is built on an axis wide enough for what it
represents (fixtures x MAX_POINTS for a player, the full convolution for a
sum). Folding a real outcome into the top bucket would otherwise make `modal`
and `p80_high` read as the ceiling on exactly the DGW rows where TC/BB get
recommended.

TODO (F4, follow-up): weak bench players carry an appearance-mass floor that
inflates the BB pmf mean relative to the sum of the bench xPts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import config, points_distribution

POS_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# Below this appearance probability the distribution is a spike at zero
# (mirrors expected_points.MIN_APPEAR_FOR_PMF).
MIN_APPEAR = 0.02


def _f(v, default=0.0):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(x) else x


def player_priors_from_elements(elements, finished_gws: int = 0) -> dict[int, dict]:
    """Per-player shape priors from the FPL bootstrap `elements`.

    Accepts the raw list of dicts or a DataFrame. Returns
    {id: {pos, xg90, xa90, p_appear, p_60}}. Missing columns degrade to
    position priors; a player flagged unavailable (chance 0) gets p_appear 0.
    """
    if elements is None:
        return {}
    el = pd.DataFrame(elements) if not isinstance(elements, pd.DataFrame) else elements
    if el.empty or "id" not in el.columns:
        return {}

    start_prior = float(getattr(config, "MINUTES_START_PRIOR", 0.55))
    prior_w = float(getattr(config, "CHIP_PLAN_DIST_PRIOR_WEIGHT", 2.0))
    p60_given = float(getattr(config, "MINUTES_P60_GIVEN_START", 0.86))
    base_xg = getattr(config, "OUTPUT_POSITION_BASE_XG90", {})
    base_xa = getattr(config, "OUTPUT_POSITION_BASE_XA90", {})
    n_gws = max(0, int(finished_gws or 0))

    def col(name):
        return el[name] if name in el.columns else pd.Series([None] * len(el), index=el.index)

    out = {}
    for pid, et, pos, xg, xa, starts, chance, status in zip(
        col("id"), col("element_type"), col("pos"),
        col("expected_goals_per_90"), col("expected_assists_per_90"),
        col("starts"), col("chance_of_playing_next_round"), col("status"),
    ):
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        pos_label = pos if isinstance(pos, str) and pos in POS_MAP.values() else POS_MAP.get(
            int(et) if pd.notna(et) else 0)
        if pos_label is None:
            continue
        xg90 = _f(xg, base_xg.get(pos_label, 0.1))
        xa90 = _f(xa, base_xa.get(pos_label, 0.1))
        if xg90 <= 0 and xa90 <= 0:
            xg90, xa90 = base_xg.get(pos_label, 0.1), base_xa.get(pos_label, 0.1)
        start_rate = (_f(starts, 0.0) + prior_w * start_prior) / (n_gws + prior_w) if n_gws + prior_w > 0 else start_prior
        start_rate = float(np.clip(start_rate, 0.0, 1.0))
        avail = 1.0 if chance is None or (isinstance(chance, float) and np.isnan(chance)) else _f(chance, 100.0) / 100.0
        if isinstance(status, str) and status.lower() in ("u", "n"):
            avail = 0.0
        p_appear = float(np.clip(start_rate * avail, 0.0, 1.0))
        out[pid] = {
            "pos": pos_label,
            "xg90": xg90,
            "xa90": xa90,
            "p_appear": p_appear,
            "p_60": p_appear * p60_given,
        }
    return out


def _pmf_for(pos, prior, n_fix, dmult, cs_prob, scale, appear_mult, max_points):
    p_appear = float(np.clip(prior["p_appear"] * appear_mult, 0.0, 1.0))
    p_60 = float(np.clip(prior["p_60"] * appear_mult, 0.0, p_appear))
    mins_share = float(getattr(config, "CHIP_PLAN_DIST_MINUTES_SHARE", 0.85))
    # Goal/assist exposure scales with the chance of being on the pitch — a
    # doubtful player's lambda shrinks with him, so a 0% player is a 0 spike.
    exposure = n_fix * mins_share * dmult * p_appear
    dc_base = float(getattr(config, "OUTPUT_DC_BASE_RATE", {}).get(pos, 0.0))
    return points_distribution.player_points_pmf(
        pos=pos,
        prob_appear=p_appear,
        prob_60=p_60,
        exp_goals=prior["xg90"] * exposure * scale,
        exp_assists=prior["xa90"] * exposure * scale,
        exp_clean_sheets=cs_prob * p_60 * n_fix * min(scale, 1.5),
        n_fixtures=n_fix,
        p_dc=dc_base * p_60,
        max_points=max_points,
    )


def axis_for(n_fixtures: int = 1) -> int:
    """Points ceiling for a player-GW pmf covering `n_fixtures` fixtures.

    `points_distribution.MAX_POINTS` sizes ONE fixture; a double gameweek can
    bank two of everything, so the axis has to grow with the fixture count or
    a big DGW captain saturates the top bucket.
    """
    return points_distribution.MAX_POINTS * max(1, int(n_fixtures or 1))


def player_gw_pmf(pos: str, xpts: float, prior: dict | None, n_fixtures: int = 1,
                  difficulty: float | None = None, appear_mult: float = 1.0) -> np.ndarray | None:
    """Points pmf for one player-GW, calibrated so its mean tracks `xpts`.

    `prior` comes from `player_priors_from_elements`; None → no distribution
    (the caller omits the shape rather than inventing one). A player with
    no fixture is a spike at zero.
    """
    if prior is None or pos not in ("GKP", "DEF", "MID", "FWD"):
        return None
    n_fix = int(n_fixtures or 0)
    max_points = axis_for(n_fix)
    if n_fix <= 0 or float(xpts) <= 0.0 or float(prior.get("p_appear", 0.0)) * appear_mult < MIN_APPEAR:
        pmf = np.zeros(max_points + 1)
        pmf[0] = 1.0
        return pmf
    mult_map = getattr(config, "CHIP_PLAN_TC_DIFF_MULT", {})
    cs_map = getattr(config, "CHIP_PLAN_CS_PROB_BY_DIFF", {})
    if difficulty is not None and np.isfinite(difficulty):
        d = int(round(float(difficulty)))
        dmult = float(mult_map.get(d, 1.0))
        cs_prob = float(cs_map.get(d, 0.33))
    else:
        dmult, cs_prob = 1.0, float(cs_map.get(3, 0.33))

    share = float(getattr(config, "CHIP_PLAN_DIST_CONTINUOUS_SHARE", {}).get(pos, 0.1))
    target = float(xpts) * (1.0 - share)

    def mean_at(scale):
        pmf = _pmf_for(pos, prior, n_fix, dmult, cs_prob, scale, appear_mult, max_points)
        return float((np.arange(pmf.size) * pmf).sum()), pmf

    lo, hi = 0.0, 6.0
    m_lo, pmf_lo = mean_at(lo)
    if target <= m_lo:
        return pmf_lo
    m_hi, pmf_hi = mean_at(hi)
    if target >= m_hi:
        return pmf_hi
    best = pmf_hi
    for _ in range(18):
        mid = 0.5 * (lo + hi)
        m_mid, best = mean_at(mid)
        if abs(m_mid - target) < 0.01:
            break
        if m_mid < target:
            lo = mid
        else:
            hi = mid
    return best


def convolve(pmfs) -> np.ndarray | None:
    """Sum of independent pmfs on an axis wide enough to hold the whole sum.

    A bench-4 of single-player pmfs lands on ~4 x MAX_POINTS. Folding the
    overflow back into a 30-point axis (the old behaviour) put ~9% of the mass
    into one bucket on exactly the bench-boost weeks worth recommending, which
    then won `modal` and clipped `p80_high`.
    """
    pmfs = [p for p in pmfs if p is not None]
    if not pmfs:
        return None
    out = np.array([1.0])
    for p in pmfs:
        out = np.convolve(out, np.asarray(p, dtype=float))
    total = out.sum()
    return out / total if total > 0 else out


def continuous_share(entries) -> float:
    """xPts share the pmf leaves out, weighted across `entries` of (pos, xpts).

    `player_gw_pmf` calibrates each pmf's mean to `xpts x (1 - share)` — bonus,
    saves and goals conceded stay continuous and are deliberately excluded. A
    bar quoted in FULL xPts therefore sits on a different axis than the pmf, so
    it must be scaled by the same factor before any P(pmf >= bar) comparison.
    """
    shares = getattr(config, "CHIP_PLAN_DIST_CONTINUOUS_SHARE", {})
    total_x = 0.0
    total_c = 0.0
    for pos, xp in entries or []:
        x = max(0.0, _f(xp, 0.0))
        total_x += x
        total_c += x * float(shares.get(pos, 0.1))
    return total_c / total_x if total_x > 0 else 0.0


def summarize(pmf: np.ndarray | None, bar: float | None = None,
              continuous_share: float = 0.0,
              player_thresholds: bool = True) -> dict | None:
    """The handful of numbers worth showing next to a chip EV.

    `continuous_share` is the fraction of xPts the pmf excludes (see
    `continuous_share()`); the bar is scaled by `1 - share` so the comparison
    happens on the pmf's own axis. `bar` is still reported in full xPts.

    `player_thresholds=False` drops `p_return`/`p_haul`/`p_blank`: those
    thresholds (6 / 10 / 2) describe ONE player, and applied to a bench-4 sum
    they saturate (~100% / ~97% / ~0%) and carry no information.
    """
    if pmf is None:
        return None
    pmf = np.asarray(pmf, dtype=float)
    points = np.arange(pmf.size)
    cdf = np.cumsum(pmf)
    top = pmf.size - 1
    low = int(np.searchsorted(cdf, 0.10))
    high = min(int(np.searchsorted(cdf, 0.90)), top)
    # The top bucket is every convolution's overflow sink — it means ">= top",
    # not "exactly top", so it can never be the single most likely score.
    modal = int(np.argmax(pmf[:-1])) if pmf.size > 1 else 0
    out = {
        "mean": round(float((points * pmf).sum()), 2),
        "modal": modal,
        "p80_low": low,
        "p80_high": high,
    }
    if high >= top and pmf[top] > 0:
        out["p80_open"] = True   # band runs off the axis: quote it as "high+"
    if player_thresholds:
        ret_at = int(getattr(config, "CHIP_PLAN_DIST_RETURN_AT", 6))
        haul_at = int(getattr(config, "CHIP_PLAN_DIST_HAUL_AT", 10))
        blank_at = int(getattr(config, "CHIP_PLAN_DIST_BLANK_AT", 2))
        out["p_return"] = round(float(pmf[ret_at:].sum()) if ret_at < pmf.size else 0.0, 3)
        out["p_haul"] = round(float(pmf[haul_at:].sum()) if haul_at < pmf.size else 0.0, 3)
        out["p_blank"] = round(float(pmf[: blank_at + 1].sum()), 3)
    if bar is not None:
        share = float(np.clip(_f(continuous_share, 0.0), 0.0, 0.95))
        # On the expiry ramp the bar decays to 0, where P(>= 0) == 1 says
        # nothing; read a non-positive bar as "any positive return clears it".
        b = max(1, int(np.ceil(float(bar) * (1.0 - share))))
        out["bar"] = round(float(bar), 2)
        out["p_beats_bar"] = round(float(pmf[b:].sum()) if b < pmf.size else 0.0, 3)
    return out
