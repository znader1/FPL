"""Derive banked free transfers under the 2026-27 rule (roll up to 5).

Pure functions; API fetch stays in the caller. The season walk replaces the
old binary 1/2 heuristic in api/main.py: FPL grants +1 FT at each new GW
deadline (cap 5), spent transfers subtract, hits floor the carry at 0, and
Wildcard/Free-Hit gameweeks consume no free transfers and grant no +1: the
saved count is maintained as-is (FPL rule since 2025/26).

GW1 is squad creation (unlimited changes, no FT concept): everyone enters
GW2 with exactly 1 FT, and banking starts from GW2's unused FT — so the
walk skips the GW1 row entirely.
"""

from src import config

_CHIP_NO_CONSUME = {"wildcard", "freehit"}


def clamp_ft(value, ft_max=None):
    if ft_max is None:
        ft_max = int(config.FT_MAX)
    if value is None:
        return None
    try:
        return max(1, min(int(ft_max), int(value)))
    except (TypeError, ValueError):
        return None


def derive_free_transfers(events, chips, next_event_id, ft_max=None):
    if ft_max is None:
        ft_max = int(config.FT_MAX)
    chip_gws = {
        int(c.get("event")) for c in (chips or [])
        if str(c.get("name") or "").lower() in _CHIP_NO_CONSUME and c.get("event") is not None
    }
    rows = sorted(
        (e for e in (events or [])
         if e.get("event") is not None and 2 <= int(e["event"]) < int(next_event_id)),
        key=lambda e: int(e["event"]),
    )
    ft = 1
    for row in rows:
        gw = int(row["event"])
        if gw in chip_gws:
            # FPL (since 2025/26) MAINTAINS saved transfers through a Wildcard
            # or Free Hit week: the count you took into the chip week is the
            # count you have next week. No spend, and no +1 either — a FH in
            # GW4 with 1 FT gives 1 FT for GW5, not 2 (verified 2026-09-18
            # against a live entry).
            continue
        used = max(0, int(row.get("event_transfers") or 0))
        ft = min(int(ft_max), max(ft - used, 0) + 1)
    return ft


def resolve_free_transfers(history, next_event_id, *, event_transfers=None,
                           squad_event_id=None, active_chip=None, ft_max=None):
    """
    The ONE way to answer "how many free transfers does this entry take into
    ``next_event_id``?" — used by /recommendations, the chat context and the
    Chips tab so they never disagree (hotfix H2, 2026-10).

    ``history`` is the raw ``/entry/{id}/history/`` payload (``current`` rows +
    ``chips``), or None when that fetch failed. With history the season walk
    above decides. Without it, fall back to the pre-2026 single-GW heuristic:
    0 transfers in the squad GW banked one (→ 2), otherwise 1 — never from
    GW1 (squad creation) and never after a Wildcard/Free Hit week.
    """
    rows = (history or {}).get("current") if isinstance(history, dict) else None
    if rows:
        return derive_free_transfers(
            rows, (history or {}).get("chips") or [], next_event_id=next_event_id, ft_max=ft_max)
    chip = str(active_chip or "").lower()
    try:
        squad_gw = int(squad_event_id) if squad_event_id is not None else 0
        used = int(event_transfers) if event_transfers is not None else None
    except (TypeError, ValueError):
        return 1
    if used is None or squad_gw < 2 or chip in _CHIP_NO_CONSUME:
        return 1
    return 2 if used == 0 else 1
