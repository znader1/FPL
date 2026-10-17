"""Projected field benchmarks (frontend handoff 1a, backend step 3).

The rail's "Projected GW" card wants three numbers next to the user's own
projected total:

    projected_top10k_avg   mean projected total of the sampled top-10k entries
    projected_overall_avg  mean projected total of entries sampled uniformly
                           across the whole league
    projected_percentile   "top N%": the share of the overall sample whose
                           projected total is strictly above the user's

Every entry's total is Σ multiplier × xPts over its picks (0 bench, 1 start,
2 captain, 3 triple captain) — the same axis as the response's
``projected_points_with_captain`` — scored against *this request's* xPts, so
the benchmarks move with the model. Hits are ignored on both sides. The
picks come from ``src/top10k_eo.py``'s sample file (``entries`` and
``overall.entries``); a file written before entries were kept still yields
the top-10k average from its EO aggregate (Σ eo_pct/100 × xPts is the same
mean) and null for the rest.
"""
from src import config
from src.utils import safe_float, safe_int


def entry_total(picks, xpts_by_id):
    """Σ multiplier × xPts over ``[[element, multiplier], ...]``; unknown players score 0."""
    total = 0.0
    for pair in picks or []:
        try:
            pid, mult = pair[0], pair[1]
        except (TypeError, IndexError):
            continue
        pid = safe_int(pid)
        if pid is None:
            continue
        total += (safe_int(mult) or 0) * safe_float(xpts_by_id.get(pid), default=0.0)
    return total


def _totals(entries, xpts_by_id):
    return [entry_total(e.get("picks"), xpts_by_id) for e in entries or [] if isinstance(e, dict)]


def _mean(xs):
    return round(sum(xs) / len(xs), 2) if xs else None


def _quantiles(xs, n=100):
    """n+1 evenly spaced quantiles (q0 = min … q100 = max), linear interpolation."""
    if not xs:
        return None
    s = sorted(xs)
    last = len(s) - 1
    out = []
    for i in range(n + 1):
        pos = last * i / n
        lo = int(pos)
        hi = min(lo + 1, last)
        out.append(round(s[lo] + (s[hi] - s[lo]) * (pos - lo), 2))
    return out


def percentile_above(totals, my_points):
    """Top-N percent: share of ``totals`` strictly above ``my_points``, floored
    so the ring never reads "top 0%". None without a field."""
    if not totals:
        return None
    above = sum(1 for t in totals if t > my_points)
    pct = 100.0 * above / len(totals)
    return round(max(float(config.FIELD_PERCENTILE_FLOOR), pct), 1)


def summarize(sample, xpts_by_id):
    """Score the sample once per request. None without a sample."""
    if not isinstance(sample, dict):
        return None
    top_entries = sample.get("entries") or []
    top_totals = _totals(top_entries, xpts_by_id)
    if top_totals:
        top_avg = _mean(top_totals)
    else:
        players = sample.get("players") or {}
        top_avg = round(sum(
            safe_float((v or {}).get("eo_pct"), default=0.0) / 100.0 * safe_float(xpts_by_id.get(safe_int(pid)), default=0.0)
            for pid, v in players.items()
        ), 2) if players else None
    overall = sample.get("overall") if isinstance(sample.get("overall"), dict) else {}
    overall_totals = _totals(overall.get("entries"), xpts_by_id)
    return {
        "event_id": safe_int(sample.get("event_id")),
        "top10k_avg": top_avg,
        "top10k_n": len(top_totals),
        "overall_avg": _mean(overall_totals),
        "overall_n": len(overall_totals),
        "overall_totals": overall_totals,
        "overall_quantiles": _quantiles(overall_totals),
    }


def fields(summary, my_points):
    """The three response keys for one projected total (base squad or a transfer step)."""
    if not isinstance(summary, dict):
        return {"projected_top10k_avg": None, "projected_overall_avg": None, "projected_percentile": None}
    return {
        "projected_top10k_avg": summary.get("top10k_avg"),
        "projected_overall_avg": summary.get("overall_avg"),
        "projected_percentile": percentile_above(summary.get("overall_totals"), safe_float(my_points, default=0.0)),
    }


def public(summary):
    """What the response carries under ``projected_field`` (quantiles let the
    client re-place a client-side total without another request)."""
    if not isinstance(summary, dict):
        return None
    return {k: summary.get(k) for k in ("event_id", "top10k_n", "overall_n", "overall_quantiles")}
