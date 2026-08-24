"""Derive banked free transfers under the 2026-27 rule (roll up to 5).

Pure functions; API fetch stays in the caller. The season walk replaces the
old binary 1/2 heuristic in api/main.py: FPL grants +1 FT at each new GW
deadline (cap 5), spent transfers subtract, hits floor the carry at 0, and
Wildcard/Free-Hit gameweeks consume no free transfers.
"""

from src import config

_CHIP_NO_CONSUME = {"wildcard", "freehit"}


def clamp_ft(value, ft_max=None):
    if ft_max is None:
        ft_max = int(getattr(config, "FT_MAX", 5))
    if value is None:
        return None
    try:
        return max(1, min(int(ft_max), int(value)))
    except (TypeError, ValueError):
        return None


def derive_free_transfers(events, chips, next_event_id, ft_max=None):
    if ft_max is None:
        ft_max = int(getattr(config, "FT_MAX", 5))
    chip_gws = {
        int(c.get("event")) for c in (chips or [])
        if str(c.get("name") or "").lower() in _CHIP_NO_CONSUME and c.get("event") is not None
    }
    rows = sorted(
        (e for e in (events or []) if e.get("event") is not None and int(e["event"]) < int(next_event_id)),
        key=lambda e: int(e["event"]),
    )
    ft = 1
    for row in rows:
        gw = int(row["event"])
        used = 0 if gw in chip_gws else max(0, int(row.get("event_transfers") or 0))
        ft = min(int(ft_max), max(ft - used, 0) + 1)
    return ft
