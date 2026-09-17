"""Per-player, per-gameweek points distributions for the chip planner.

The chip EV is a mean and stays a mean (expectation is the right objective).
But "Triple Captain in GW12 projects +9.1" hides the decision a manager is
really weighing — is that a safe 7 or a coin-flip between 2 and 18? This
module gives every model-zone chip candidate the shape behind its number:

* P(return)  — the captain (TC) / bench (BB) scores at least `RETURN_AT`
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


def _pmf_for(pos, prior, n_fix, dmult, cs_prob, scale, appear_mult):
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
    )


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
    if n_fix <= 0 or float(xpts) <= 0.0 or float(prior.get("p_appear", 0.0)) * appear_mult < MIN_APPEAR:
        pmf = np.zeros(points_distribution.MAX_POINTS + 1)
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
        pmf = _pmf_for(pos, prior, n_fix, dmult, cs_prob, scale, appear_mult)
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
    """Sum of independent pmfs, overflow folded into the top bucket."""
    pmfs = [p for p in pmfs if p is not None]
    if not pmfs:
        return None
    max_points = points_distribution.MAX_POINTS
    out = np.zeros(max_points + 1)
    out[0] = 1.0
    for p in pmfs:
        full = np.convolve(out, p)
        head = full[: max_points + 1].copy()
        if full.size > max_points + 1:
            head[max_points] += full[max_points + 1:].sum()
        out = head
    total = out.sum()
    return out / total if total > 0 else out


def summarize(pmf: np.ndarray | None, bar: float | None = None) -> dict | None:
    """The handful of numbers worth showing next to a chip EV."""
    if pmf is None:
        return None
    pmf = np.asarray(pmf, dtype=float)
    points = np.arange(pmf.size)
    cdf = np.cumsum(pmf)
    ret_at = int(getattr(config, "CHIP_PLAN_DIST_RETURN_AT", 6))
    haul_at = int(getattr(config, "CHIP_PLAN_DIST_HAUL_AT", 10))
    blank_at = int(getattr(config, "CHIP_PLAN_DIST_BLANK_AT", 2))
    low = int(np.searchsorted(cdf, 0.10))
    high = min(int(np.searchsorted(cdf, 0.90)), pmf.size - 1)
    out = {
        "mean": round(float((points * pmf).sum()), 2),
        "modal": int(np.argmax(pmf)),
        "p_return": round(float(pmf[ret_at:].sum()) if ret_at < pmf.size else 0.0, 3),
        "p_haul": round(float(pmf[haul_at:].sum()) if haul_at < pmf.size else 0.0, 3),
        "p_blank": round(float(pmf[: blank_at + 1].sum()), 3),
        "p80_low": low,
        "p80_high": high,
    }
    if bar is not None:
        b = max(0, int(np.ceil(float(bar))))
        out["bar"] = round(float(bar), 2)
        out["p_beats_bar"] = round(float(pmf[b:].sum()) if b < pmf.size else 0.0, 3)
    return out
