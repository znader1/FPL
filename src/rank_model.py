"""Rank gain if a captain hauls (frontend handoff 1b, step 2 of the backend numbers).

    relative points vs the field = haul × (2 − field_EO/100)
        you double him; the average rival effectively holds field_EO/100 of him
    ranks gained = relative points × ranks per point around your rank
        capped at rank 1

Ranks per point comes from two pages of the overall league's standings: the
page holding your rank and the one half-way up (``RANK_MODEL_SPAN``), so the
slope is local to where you sit — a point is worth ~40k ranks at 1.6M and a
few hundred near the top. Two standings calls, cached per GW and rank bucket.

Field EO: inside the top 10k the sampled top-10k EO *is* the field. Outside,
the top 10k's picks say little about rank 1.6M, so the field is overall
ownership (FPL's selected_by_percent) scaled by the sample's captaining share
(captained / owned among top-10k owners) — the best available proxy for how
much of the field doubles him.
"""
import logging
import math
import time

from src import config, fpl_client
from src.utils import safe_float, safe_int

logger = logging.getLogger(__name__)


def relative_points(haul_points, field_eo_pct):
    """Points gained on the average rival when the captain scores ``haul_points``."""
    h = safe_float(haul_points, default=None)
    eo = safe_float(field_eo_pct, default=None)
    if h is None or eo is None:
        return None
    return max(0.0, float(h) * (2.0 - float(eo) / 100.0))


def rank_gain_if_haul(haul_points, field_eo_pct, ranks_per_point, overall_rank):
    rel = relative_points(haul_points, field_eo_pct)
    rpp = safe_float(ranks_per_point, default=None)
    rank = safe_int(overall_rank)
    if rel is None or rpp is None or rank is None or rank < 1:
        return None
    gain = int(round(rel * float(rpp)))
    return max(0, min(gain, rank - 1))


def ranks_per_point(samples):
    """``samples``: [(rank, total_points), ...] — at least two distinct totals."""
    pts = [(safe_int(r), safe_float(t, default=None)) for r, t in (samples or [])]
    pts = [(r, t) for r, t in pts if r is not None and t is not None]
    if len(pts) < 2:
        return None
    (r1, t1), (r2, t2) = pts[0], pts[-1]
    d_points = t2 - t1
    d_rank = r1 - r2
    if d_points <= 0 or d_rank <= 0:
        return None
    return float(d_rank) / float(d_points)


def field_eo_pct(sample, ownership_pct, overall_rank):
    """What share of the field, around ``overall_rank``, effectively holds him."""
    rank = safe_int(overall_rank)
    if rank is None:
        return None
    if rank <= int(config.RANK_MODEL_TOP10K_CUTOFF):
        if isinstance(sample, dict):
            eo = safe_float(sample.get("eo_pct"), default=None)
            if eo is not None:
                return round(float(eo), 1)
        return None
    own = safe_float(ownership_pct, default=None)
    if own is None:
        return None
    share = 0.0
    if isinstance(sample, dict):
        owned = safe_float(sample.get("owned_pct"), default=None)
        capt = safe_float(sample.get("captained_pct"), default=None)
        if owned and capt is not None and owned > 0:
            share = float(capt) / float(owned)
    return round(float(own) * (1.0 + share), 1)


def _page_for(rank, page_size):
    return max(1, int(math.ceil(float(rank) / float(page_size))))


def _page_point(payload, want_rank):
    rows = ((payload or {}).get("standings") or {}).get("results") or []
    best = None
    for row in rows:
        r = safe_int(row.get("rank"))
        t = safe_float(row.get("total"), default=None)
        if r is None or t is None:
            continue
        if best is None or abs(r - want_rank) < abs(best[0] - want_rank):
            best = (r, t)
    return best


_cache = {}


def build(overall_rank, event_id, fetch_standings=None, session=None):
    """``{overall_rank, ranks_per_point, basis, event_id, sampled}`` or None.

    None when the entry has no rank yet, sits at rank 1, or the standings
    could not be read — the records then carry no rank gain, honestly.
    """
    rank = safe_int(overall_rank)
    if rank is None or rank <= 1:
        return None
    fetch_standings = fetch_standings or fpl_client.get_classic_league_standings
    page_size = int(config.RANK_MODEL_PAGE_SIZE)
    bucket = rank // int(config.RANK_MODEL_CACHE_BUCKET)
    key = (safe_int(event_id), bucket)
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit["ts"] < float(config.RANK_MODEL_TTL):
        return {**hit["data"], "overall_rank": rank} if hit["data"] else None

    upper_rank = max(1, int(rank * float(config.RANK_MODEL_SPAN)))
    pages = [_page_for(rank, page_size), _page_for(upper_rank, page_size)]
    data = None
    try:
        points = []
        for page, want in zip(pages, (rank, upper_rank)):
            pt = _page_point(fetch_standings(int(config.TOP10K_EO_LEAGUE_ID), page=page, session=session), want)
            if pt:
                points.append(pt)
        rpp = ranks_per_point(points)
        if rpp is not None:
            data = {
                "ranks_per_point": round(rpp, 1),
                "basis": "top10k" if rank <= int(config.RANK_MODEL_TOP10K_CUTOFF) else "overall",
                "event_id": safe_int(event_id),
                "sampled": [{"rank": r, "total": t} for r, t in points],
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("rank model: standings read failed for rank %s: %s", rank, exc)
        return None
    _cache[key] = {"ts": now, "data": data}
    return {**data, "overall_rank": rank} if data else None
