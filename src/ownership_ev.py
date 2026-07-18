"""
Ownership-adjusted differential EV for mini-league strategy.

differential_ev = (xpts_horizon - template_xpts[pos]) * (1 - league_ownership)

template_xpts[pos] is the GLOBAL-ownership-weighted (selected_by_percent) average
projected points at a position — "what the field effectively gets" — so the EV
measures points gained over the template, scaled by how differentiated the pick is
within your specific mini-league (league_ownership).

Pure module: no I/O, no global state. All tunables live in ``config``.
"""
from __future__ import annotations

try:
    from . import config
except Exception:  # pragma: no cover - flat script usage
    import config  # type: ignore


def _to_float(v, default=0.0):
    try:
        return float(v if v is not None else default)
    except (TypeError, ValueError):
        return default


def xpts_of(meta):
    """model_xpts_horizon, else ep_next, else 0.0."""
    v = meta.get("model_xpts_horizon")
    if v is None:
        v = meta.get("ep_next")
    return _to_float(v, 0.0)


def compute_position_templates(elements_meta):
    """
    {position_id: global-ownership-weighted average xpts at that position}.
    Falls back to the simple mean for a position whose total ownership is 0.
    """
    sums = {}    # pos -> [weighted_xpts_sum, weight_sum, xpts_sum, count]
    for meta in (elements_meta or {}).values():
        pos = meta.get("position_id")
        if pos is None:
            continue
        w = _to_float(meta.get("selected_by_percent"), 0.0)
        x = xpts_of(meta)
        acc = sums.setdefault(int(pos), [0.0, 0.0, 0.0, 0])
        acc[0] += w * x
        acc[1] += w
        acc[2] += x
        acc[3] += 1
    out = {}
    for pos, (wx, w, sx, n) in sums.items():
        out[pos] = (wx / w) if w > 0 else (sx / n if n else 0.0)
    return out


def differential_ev(xpts_horizon, template_xpts_pos, league_ownership):
    """(xpts - template) * (1 - clip(league_ownership, 0, 1))."""
    own = _to_float(league_ownership, 0.0)
    own = min(1.0, max(0.0, own))
    return (_to_float(xpts_horizon) - _to_float(template_xpts_pos)) * (1.0 - own)


def annotate_candidates(candidates, templates):
    """Return a new list of candidate rows, each with differential_ev + template_xpts."""
    out = []
    for c in candidates or []:
        row = dict(c)
        pos = c.get("position_id")
        template = _to_float((templates or {}).get(int(pos) if pos is not None else -1, 0.0))
        row["template_xpts"] = round(template, 3)
        row["differential_ev"] = round(
            differential_ev(xpts_of(c), template, c.get("league_ownership")), 3
        )
        out.append(row)
    return out
