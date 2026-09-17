"""International-break detection from the FPL events calendar.

No hardcoded dates: a GW whose deadline sits unusually long after the previous
GW's deadline (normal cadence ~7 days; international windows produce ~14) is
flagged as the first GW after a break. Downstream, chip recommendations for
such GWs carry an uncertainty haircut and a "wait for team news" nudge flag.
"""
from __future__ import annotations
import pandas as pd
from src import config


def international_break_gws(events: list[dict], gap_days: float | None = None) -> dict[int, dict]:
    """Map event_id -> {"gap_days", "prev_event"} for post-break GWs.

    Malformed rows are skipped; any failure mode degrades to an empty map,
    which downstream treats as "no breaks known".
    """
    gap = float(gap_days if gap_days is not None else getattr(config, "BREAK_GAP_DAYS", 10.0))
    parsed = []
    for e in events or []:
        try:
            eid = int(e.get("id"))
            ts = pd.Timestamp(e.get("deadline_time"))
        except (TypeError, ValueError):
            continue
        if pd.isna(ts):
            continue
        parsed.append((eid, ts))
    parsed.sort(key=lambda x: x[0])

    out: dict[int, dict] = {}
    for (prev_id, prev_ts), (eid, ts) in zip(parsed, parsed[1:]):
        delta_days = (ts - prev_ts).total_seconds() / 86400.0
        if delta_days > gap:
            out[eid] = {"gap_days": round(delta_days, 1), "prev_event": prev_id}
    return out
