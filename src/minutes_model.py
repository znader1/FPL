"""
Minutes model: probability of starting and expected minutes per player per GW.

Combines two signals:

1. **History** — a time-decayed (by GW recency) estimate of each player's start
   rate, their average minutes when they start, and their appearance rate when
   they don't. Built from the processed ``player_gw_history`` table
   (``gw_minutes``, ``gw_starts``).
2. **Availability** — the live FPL ``chance_of_playing_next_round`` and
   ``status`` fields, which capture injuries/suspensions the history can't.

Outputs, per player:
    prob_start   P(in the starting XI)
    prob_appear  P(plays at least 1 minute)
    prob_60      P(plays >= 60 minutes)  -> needed for CS / 2-pt appearance
    exp_minutes  expected minutes played

``output_model.py`` uses ``exp_minutes`` to scale per-90 attacking output and
``prob_60`` for clean-sheet and appearance points.

All tunables live in ``config`` (``MINUTES_*``).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

try:
    from . import config
except Exception:  # pragma: no cover - flat script usage
    import config  # type: ignore


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def find_latest_gw_history(base_dir="data/processed/fpl"):
    """Newest ``player_gw_history_*.csv`` under base_dir (mirrors projections.py)."""
    base = Path(base_dir)
    if not base.exists():
        return None
    paths = list(base.glob("*/player_gw_history_*.csv"))
    if not paths:
        paths = list(base.glob("player_gw_history_*.csv"))
    if not paths:
        return None
    return str(max(paths, key=lambda p: p.stat().st_mtime))


_minutes_history_cache = {"key": None, "df": None}


def load_minutes_history(path=None, base_dir="data/processed/fpl"):
    """
    Load player-by-GW minutes history. Returns columns
    ``player_id, gw, gw_minutes, gw_starts`` (or empty if unavailable).
    """
    selected = str(path or find_latest_gw_history(base_dir=base_dir) or "")
    if not selected or not Path(selected).exists():
        return pd.DataFrame()
    # Cached on (path, mtime, size) — same reasoning as the match history: this
    # file is re-read on every model build, and a refresh rewrites it, which
    # changes the key.
    try:
        stat = Path(selected).stat()
        key = (selected, stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = None
    if key is not None and _minutes_history_cache["key"] == key:
        return _minutes_history_cache["df"]
    try:
        df = pd.read_csv(selected)
    except Exception:
        return pd.DataFrame()

    if any(c not in df.columns for c in ["player_id", "gw"]):
        return pd.DataFrame()
    out = pd.DataFrame()
    out["player_id"] = pd.to_numeric(df["player_id"], errors="coerce")
    out["gw"] = pd.to_numeric(df["gw"], errors="coerce")
    out["gw_minutes"] = pd.to_numeric(df.get("gw_minutes", 0), errors="coerce").fillna(0.0)
    if "gw_starts" in df.columns:
        out["gw_starts"] = pd.to_numeric(df["gw_starts"], errors="coerce").fillna(0.0)
    else:
        # Fallback proxy when starts aren't tracked: >=60 minutes implies a start.
        out["gw_starts"] = (out["gw_minutes"] >= 60).astype(float)
    out = out[out["player_id"].notna() & out["gw"].notna()].copy()
    out["player_id"] = out["player_id"].astype(int)
    out["gw"] = out["gw"].astype(int)
    out = out.reset_index(drop=True)
    if key is not None:
        _minutes_history_cache["key"] = key
        _minutes_history_cache["df"] = out
    return out


# ---------------------------------------------------------------------------
# Decayed history features
# ---------------------------------------------------------------------------

def _gw_decay_weights(gws, asof_gw, halflife_gws):
    """Half-life weights based on how many GWs ago each row is."""
    halflife = max(1e-6, float(halflife_gws))
    age = (float(asof_gw) - pd.to_numeric(pd.Series(gws), errors="coerce")).clip(lower=0.0)
    return np.power(0.5, age / halflife).astype("float64")


def compute_minutes_features(history_df, gw, halflife_gws=None):
    """
    Decayed per-player start/minutes features from history strictly before ``gw``.

    Returns columns:
        player_id, hist_start_rate, hist_min_given_start,
        hist_appear_rate, eff_samples
    """
    halflife_gws = float(halflife_gws if halflife_gws is not None
                         else getattr(config, "MINUTES_HALFLIFE_GWS", 5.0))
    if history_df is None or history_df.empty:
        return pd.DataFrame(columns=[
            "player_id", "hist_start_rate", "hist_min_given_start",
            "hist_appear_rate", "eff_samples",
        ])

    df = history_df[history_df["gw"] < int(gw)].copy()
    if df.empty:
        return pd.DataFrame(columns=[
            "player_id", "hist_start_rate", "hist_min_given_start",
            "hist_appear_rate", "eff_samples",
        ])

    df["w"] = _gw_decay_weights(df["gw"], int(gw), halflife_gws)
    df["started"] = (df["gw_starts"] > 0).astype(float)
    df["appeared"] = (df["gw_minutes"] > 0).astype(float)
    # Minutes only count toward "given start" when the player actually started.
    df["start_minutes"] = df["gw_minutes"].where(df["started"] > 0, 0.0)

    rows = []
    for pid, g in df.groupby("player_id"):
        wsum = float(g["w"].sum())
        if wsum <= 0:
            continue
        start_rate = float((g["started"] * g["w"]).sum() / wsum)
        appear_rate = float((g["appeared"] * g["w"]).sum() / wsum)
        start_w = float((g["started"] * g["w"]).sum())
        if start_w > 0:
            min_given_start = float((g["start_minutes"] * g["w"]).sum() / start_w)
        else:
            min_given_start = float(getattr(config, "MINUTES_E_MIN_GIVEN_START", 82.0))
        rows.append({
            "player_id": int(pid),
            "hist_start_rate": start_rate,
            "hist_min_given_start": min_given_start,
            "hist_appear_rate": appear_rate,
            "eff_samples": wsum,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Availability from live elements
# ---------------------------------------------------------------------------

def _availability_series(elements_df):
    """
    Per-player availability probability in [0, 1] from ``chance_of_playing_next_round``
    capped by the hard ``status`` map. Index aligns with ``elements_df``.
    """
    n = len(elements_df)
    idx = elements_df.index
    chance = pd.to_numeric(elements_df.get("chance_of_playing_next_round"), errors="coerce")
    chance_this = pd.to_numeric(elements_df.get("chance_of_playing_this_round"), errors="coerce")
    chance = chance.where(chance.notna(), chance_this)
    avail = (chance / 100.0).clip(lower=0.0, upper=1.0)
    avail = avail.fillna(1.0)  # unknown -> assume available

    status_map = getattr(config, "MINUTES_STATUS_AVAILABILITY", {})
    if "status" in elements_df.columns:
        status_cap = elements_df["status"].astype(str).str.strip().str.lower().map(status_map)
        status_cap = pd.to_numeric(status_cap, errors="coerce").fillna(1.0)
        avail = pd.concat([avail, status_cap], axis=1).min(axis=1)
    return pd.Series(avail.values, index=idx, dtype="float64") if n else pd.Series(dtype="float64")


# ---------------------------------------------------------------------------
# Public projection
# ---------------------------------------------------------------------------

def minutes_projection(elements_df, history_df, gw):
    """
    Project starting probability and expected minutes for every element.

    ``elements_df`` must carry an ``id`` column; ``status`` /
    ``chance_of_playing_next_round`` are used when present. ``history_df`` is the
    output of ``load_minutes_history`` (may be empty).

    Returns a DataFrame indexed by player id (``id``) with:
        prob_start, prob_appear, prob_60, exp_minutes
    """
    start_prior = float(getattr(config, "MINUTES_START_PRIOR", 0.55))
    prior_w = float(getattr(config, "MINUTES_PRIOR_WEIGHT", 2.0))
    e_min_start_default = float(getattr(config, "MINUTES_E_MIN_GIVEN_START", 82.0))
    cameo = float(getattr(config, "MINUTES_CAMEO_MINUTES", 22.0))
    sub_app_prob = float(getattr(config, "MINUTES_SUB_APP_PROB", 0.45))
    p60_given_start = float(getattr(config, "MINUTES_P60_GIVEN_START", 0.86))

    df = elements_df.copy()
    if "id" not in df.columns:
        return pd.DataFrame(columns=[
            "prob_start", "prob_appear", "prob_60", "exp_minutes",
            "rotation_prob_start", "availability",
        ])
    df["id"] = pd.to_numeric(df["id"], errors="coerce")
    df = df[df["id"].notna()].copy()
    df["id"] = df["id"].astype(int)

    feats = compute_minutes_features(history_df, int(gw))
    if not feats.empty:
        df = df.merge(feats, left_on="id", right_on="player_id", how="left")
    else:
        for c in ["hist_start_rate", "hist_min_given_start", "hist_appear_rate", "eff_samples"]:
            df[c] = np.nan

    eff = pd.to_numeric(df.get("eff_samples"), errors="coerce").fillna(0.0)
    hist_start = pd.to_numeric(df.get("hist_start_rate"), errors="coerce")
    hist_appear = pd.to_numeric(df.get("hist_appear_rate"), errors="coerce")
    hist_min_start = pd.to_numeric(df.get("hist_min_given_start"), errors="coerce")

    # Shrink the historical start rate toward the prior using effective samples.
    blended_start = ((hist_start.fillna(start_prior) * eff) + (start_prior * prior_w)) / (eff + prior_w)
    # When there's literally no history, fall back fully to the prior.
    blended_start = blended_start.where(eff > 0, start_prior).clip(0.0, 1.0)

    e_min_given_start = hist_min_start.where(hist_min_start.notna(), e_min_start_default).clip(1.0, 90.0)

    avail = _availability_series(df)

    prob_start = (blended_start * avail).clip(0.0, 1.0)
    # Appearance when not starting (cameo off the bench), also gated by availability.
    base_appear = prob_start + (1.0 - prob_start) * sub_app_prob
    # Don't let a strong historical appearance rate be ignored.
    base_appear = pd.concat(
        [base_appear, hist_appear.fillna(0.0)], axis=1
    ).max(axis=1)
    prob_appear = (base_appear * avail).clip(0.0, 1.0)
    prob_appear = pd.concat([prob_appear, prob_start], axis=1).max(axis=1)  # appear >= start

    prob_60 = (prob_start * p60_given_start).clip(0.0, 1.0)

    exp_minutes = (
        prob_start * e_min_given_start
        + (prob_appear - prob_start).clip(lower=0.0) * cameo
    ).clip(0.0, 90.0)

    out = pd.DataFrame({
        "prob_start": prob_start.values,
        "prob_appear": prob_appear.values,
        "prob_60": prob_60.values,
        "exp_minutes": exp_minutes.values,
        "rotation_prob_start": blended_start.clip(0.0, 1.0).values,
        "availability": avail.values,
    }, index=df["id"].values)
    out.index.name = "id"
    return out


def rotation_minutes_multiplier(prob_start_eff, prob_appear=None,
                                nailed_ref=None, cameo_value=None):
    """
    Relative rotation-risk multiplier in [0, 1].

    Nailed starters (prob_start_eff >= nailed_ref) map to 1.0; below that they are
    linearly discounted, plus a small cameo bonus for likely bench appearances.
    NaN prob_start_eff -> 1.0 (no discount / missing data). When prob_appear is
    provided but NaN for an entry, that entry falls back to prob_start_eff (zero
    cameo).

    Accepts scalars, lists, or Series. Arithmetic is positional (a caller's Series
    index never causes silent label-alignment); the primary input's index is
    restored on the returned Series. If ``prob_appear`` is provided, its length
    must be 1 (broadcast) or equal to ``prob_start_eff``'s length — any other
    length raises ``ValueError`` rather than silently reintroducing NaN via
    misaligned positional arithmetic.
    """
    nailed_ref = float(nailed_ref if nailed_ref is not None
                       else getattr(config, "MINUTES_NAILED_START_REF", 0.85))
    cameo_value = float(cameo_value if cameo_value is not None
                        else getattr(config, "MINUTES_CAMEO_POINT_VALUE", 0.30))
    nailed_ref = max(1e-6, nailed_ref)

    ps = pd.to_numeric(pd.Series(prob_start_eff).reset_index(drop=True), errors="coerce")
    if prob_appear is None:
        pa = ps.copy()
    else:
        pa = pd.Series(prob_appear).reset_index(drop=True)
        if len(pa) == 1 and len(ps) != 1:
            pa = pd.Series([pa.iloc[0]] * len(ps))
        elif len(pa) != len(ps):
            raise ValueError(
                f"rotation_minutes_multiplier: prob_appear has length {len(pa)}, "
                f"which is neither 1 nor len(prob_start_eff) ({len(ps)}). "
                "Ragged-length inputs are rejected because subsequent positional "
                "arithmetic would silently misalign and reintroduce NaN."
            )
        pa = pd.to_numeric(pa, errors="coerce")
        pa = pa.where(pa.notna(), ps)

    rot = (ps / nailed_ref).clip(0.0, 1.0)
    cameo = (pa - ps).clip(lower=0.0) * cameo_value
    mult = (rot + cameo).clip(0.0, 1.0)
    mult = mult.where(ps.notna(), 1.0)

    if isinstance(prob_start_eff, pd.Series):
        mult.index = prob_start_eff.index
    return mult


def compute_gw_minutes_multiplier(mins_df, ids, gw_offset, injury_future_fade=None):
    """
    Map a minutes_projection frame onto `ids` and return the rotation-risk
    multiplier positionally aligned to `ids` (RangeIndex).

    gw_offset 0 = immediate GW (full availability). gw_offset >= 1 fades only the
    injury/availability component (injuries resolve) while the history-based
    rotation discount stays at full strength.
    """
    fade = float(injury_future_fade if injury_future_fade is not None
                 else getattr(config, "PROJ_INJURY_FUTURE_GW_FADE", 0.5))
    ids = pd.Series(list(ids)).reset_index(drop=True)
    if mins_df is None or mins_df.empty:
        return pd.Series([1.0] * len(ids))

    rot = ids.map(mins_df["rotation_prob_start"]).astype("float64")
    avail = ids.map(mins_df["availability"]).astype("float64")
    appear = ids.map(mins_df["prob_appear"]).astype("float64")

    if int(gw_offset) <= 0:
        avail_eff = avail
    else:
        avail_eff = 1.0 - (1.0 - avail) * fade

    prob_start_eff = rot * avail_eff
    mult = rotation_minutes_multiplier(prob_start_eff, appear)
    return mult.where(mult.notna(), 1.0).reset_index(drop=True)
