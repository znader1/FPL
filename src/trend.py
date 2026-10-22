"""
Per-player trend: direction of underlying output, not its level (spec 4.3).

Attackers (element_type 3, 4): per-90 xG + xA over the last `w` matches minus
the same over the `w` before. Defenders / keepers (1, 2): the reverse of the
xGC-against change plus the change in defensive-contribution rate. `w` =
min(CHIP_WILDCARD_TREND_WINDOW, n // 2), shrunk by n / (n + SHRINK) and
clipped to ±CHIP_WILDCARD_TREND_CLIP. Fewer than two matches → 0.
"""
from __future__ import annotations

import pandas as pd

from . import config

REQUIRED = ["element", "element_type", "event", "minutes", "expected_goals",
            "expected_assists", "expected_goals_conceded", "defensive_contribution"]


def _per90(num, minutes):
    mins = float(minutes)
    return float(num) * 90.0 / mins if mins > 0 else 0.0


def player_trend(match_df, as_of_event):
    """→ DataFrame[element, trend]. Only matches with event < as_of_event count."""
    if match_df is None or match_df.empty or any(c not in match_df.columns for c in REQUIRED):
        return pd.DataFrame(columns=["element", "trend"])
    df = match_df[REQUIRED].copy()
    for c in REQUIRED:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["event"].notna() & (df["event"] < int(as_of_event)) & (df["minutes"].fillna(0) > 0)]
    df = df.sort_values(["element", "event"])

    window = int(config.CHIP_WILDCARD_TREND_WINDOW)
    clip = float(config.CHIP_WILDCARD_TREND_CLIP)
    shrink = float(config.CHIP_WILDCARD_TREND_SHRINK_GAMES)

    rows = []
    for element, g in df.groupby("element"):
        n = int(len(g))
        w = min(window, n // 2)
        if n < 2 or w < 1:
            rows.append({"element": int(element), "trend": 0.0})
            continue
        recent, prior = g.tail(w), g.iloc[-2 * w:-w]
        etype = int(pd.to_numeric(g["element_type"], errors="coerce").iloc[-1] or 3)

        def block(part):
            mins = float(part["minutes"].sum())
            xgi = _per90(part["expected_goals"].sum() + part["expected_assists"].sum(), mins)
            xgc = _per90(part["expected_goals_conceded"].sum(), mins)
            dc = _per90(part["defensive_contribution"].sum(), mins)
            return xgi, xgc, dc

        r_xgi, r_xgc, r_dc = block(recent)
        p_xgi, p_xgc, p_dc = block(prior)
        if etype in (1, 2):
            raw = (p_xgc - r_xgc) + (r_dc - p_dc) / 10.0
        else:
            raw = r_xgi - p_xgi
        raw *= n / (n + shrink)
        rows.append({"element": int(element), "trend": float(max(-clip, min(clip, raw)))})
    return pd.DataFrame(rows, columns=["element", "trend"])
