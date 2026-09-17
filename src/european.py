"""European midweek congestion + domestic-cup clash signals for the chip planner.

The FPL API carries no Champions League / Europa / Conference League calendar
and no FA Cup / EFL Cup dates, so both live in a user-maintained JSON file
(`data/models/european_calendar.json`, same pattern as
`knowledge_discount.json`): which Premier League teams are in which
competition this season, the competition matchday date spans, and the cup
weekends that historically turn into blank gameweeks.

Everything here is pure (events list + calendar dict in, plain dicts out) so
the chip engine stays dependency-injectable. Any malformed input degrades to
"no European weeks known" rather than raising.

Windowing: FPL gameweek `g` runs from its own deadline to the next event's
deadline. A team is in a European week for `g` when a matchday of its
competition falls inside that window (the midweek AFTER the weekend round —
managers rest players in the league game before a big tie) or within
`CHIP_PLAN_EURO_WINDOW_BEFORE_DAYS` before the deadline (the midweek leading
INTO the round — travel fatigue and late rotation). One Tuesday tie therefore
marks both the GW before it and the GW after it, which is the real effect.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from src import config

logger = logging.getLogger(__name__)

DEFAULT_CALENDAR_PATH = "data/models/european_calendar.json"
COMPETITIONS = ("ucl", "uel", "uecl")
COMPETITION_LABELS = {"ucl": "Champions League", "uel": "Europa League", "uecl": "Conference League"}


def load_european_calendar(path: str | None = None) -> dict:
    """Read the calendar file; `{}` when missing or malformed (never raises)."""
    p = Path(path or DEFAULT_CALENDAR_PATH)
    try:
        if not p.is_file():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - calendar is optional
        logger.warning("european calendar unreadable at %s", p, exc_info=True)
        return {}


def normalize_calendar_teams(calendar: dict, aliases: dict[str, str] | None) -> dict:
    """Rewrite the `teams` keys to the labels the chip engine's markets use.

    `aliases` maps any accepted spelling (FPL full name, short_name, numeric
    id as string) to the canonical label. Unknown keys are kept as-is so a
    calendar keyed on canonical names works without an alias map.
    """
    if not calendar or not isinstance(calendar.get("teams"), dict):
        return calendar
    aliases = aliases or {}
    teams = {}
    for key, comp in calendar["teams"].items():
        comp = str(comp or "").lower()
        if comp not in COMPETITIONS:
            continue
        teams[aliases.get(str(key), str(key))] = comp
    out = dict(calendar)
    out["teams"] = teams
    return out


def _parse_events(events) -> list[tuple[int, pd.Timestamp]]:
    parsed = []
    for e in events or []:
        try:
            eid = int(e.get("id"))
            ts = pd.Timestamp(e.get("deadline_time"))
        except (TypeError, ValueError, AttributeError):
            continue
        if pd.isna(ts):
            continue
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        parsed.append((eid, ts))
    parsed.sort(key=lambda x: x[0])
    return parsed


def gw_windows(events) -> dict[int, tuple[pd.Timestamp, pd.Timestamp]]:
    """event_id -> (deadline, next deadline). The last event closes 7 days later."""
    parsed = _parse_events(events)
    out = {}
    for i, (eid, ts) in enumerate(parsed):
        end = parsed[i + 1][1] if i + 1 < len(parsed) else ts + pd.Timedelta(days=7)
        out[eid] = (ts, end)
    return out


def _parse_dates(values) -> list[pd.Timestamp]:
    dates = []
    for v in values or []:
        try:
            ts = pd.Timestamp(v)
        except (TypeError, ValueError):
            continue
        if not pd.isna(ts):
            if ts.tzinfo is not None:
                ts = ts.tz_convert("UTC").tz_localize(None)
            dates.append(ts.normalize())
    return dates


def _classify(dates, start, end, before_days):
    """'before' | 'after' | 'both' | None for a matchday span vs a GW window."""
    before = any(start - pd.Timedelta(days=before_days) <= d < start for d in dates)
    after = any(start <= d < end for d in dates)
    if before and after:
        return "both"
    if before:
        return "before"
    if after:
        return "after"
    return None


def european_weeks_by_gw(events, calendar: dict, before_days: float | None = None) -> dict[int, dict[str, dict]]:
    """gw -> {team_label: {competition, label, when, days_before}}.

    `when` is "before" (tie in the midweek leading into the GW), "after"
    (tie in the midweek following the GW's round) or "both".
    """
    if not calendar or not isinstance(calendar.get("teams"), dict):
        return {}
    before_days = float(before_days if before_days is not None
                        else getattr(config, "CHIP_PLAN_EURO_WINDOW_BEFORE_DAYS", 5))
    windows = gw_windows(events)
    if not windows:
        return {}

    matchdays = []
    for md in calendar.get("matchdays") or []:
        if not isinstance(md, dict):
            continue
        comp = str(md.get("competition", "")).lower()
        if comp not in COMPETITIONS:
            continue
        dates = _parse_dates(md.get("dates"))
        if dates:
            matchdays.append((comp, str(md.get("label") or ""), dates))

    teams_by_comp: dict[str, list[str]] = {}
    for team, comp in calendar["teams"].items():
        comp = str(comp).lower()
        if comp in COMPETITIONS:
            teams_by_comp.setdefault(comp, []).append(str(team))

    out: dict[int, dict[str, dict]] = {}
    for gw, (start, end) in windows.items():
        for comp, label, dates in matchdays:
            when = _classify(dates, start, end, before_days)
            if when is None:
                continue
            # Only a leg inside the "before" window is the midweek leading INTO
            # this GW — an earlier matchday elsewhere in the season is not, and
            # an "after" week has no lead-in leg at all.
            cutoff = start - pd.Timedelta(days=before_days)
            days_before = min(
                (int((start - d).days) for d in dates if cutoff <= d < start),
                default=None)
            for team in teams_by_comp.get(comp, []):
                slot = out.setdefault(gw, {})
                prev = slot.get(team)
                if prev and prev["when"] != when:
                    when_merged = "both"
                else:
                    when_merged = when
                # Several matchdays can lead into the same GW; the nearest tie
                # is the one the risk line should quote.
                prev_days = (prev or {}).get("days_before")
                if days_before is None:
                    merged_days = prev_days
                elif prev_days is None:
                    merged_days = days_before
                else:
                    merged_days = min(days_before, prev_days)
                slot[team] = {
                    "competition": comp,
                    "label": label,
                    "when": when_merged,
                    "days_before": merged_days,
                }
    return out


def cup_clashes_by_gw(events, calendar: dict) -> dict[int, dict]:
    """gw -> {competition, label, likely_blank} for domestic-cup rounds whose
    dates fall inside the GW's window (a clash that usually blanks the GW)."""
    if not calendar:
        return {}
    windows = gw_windows(events)
    out: dict[int, dict] = {}
    for rnd in calendar.get("cup_rounds") or []:
        if not isinstance(rnd, dict):
            continue
        dates = _parse_dates(rnd.get("dates"))
        if not dates:
            continue
        for gw, (start, end) in windows.items():
            if any(start <= d < end for d in dates):
                out[gw] = {
                    "competition": str(rnd.get("competition") or "cup"),
                    "label": str(rnd.get("label") or ""),
                    "likely_blank": bool(rnd.get("likely_blank", False)),
                }
    return out


def discount_projections(gw_projections: dict[int, pd.DataFrame],
                         euro_by_gw: dict[int, dict[str, dict]] | None,
                         mult: float | None = None) -> dict[int, pd.DataFrame]:
    """Scale `xpts` of every player whose team is in a European week that GW.

    Returns a new dict (untouched frames are shared, discounted ones copied).
    A mult of 1.0 or an empty map returns the input as-is.
    """
    mult = float(mult if mult is not None else getattr(config, "CHIP_PLAN_EURO_XPTS_MULT", 1.0))
    if not euro_by_gw or mult >= 1.0 or mult <= 0.0:
        return gw_projections
    out = {}
    for gw, market in gw_projections.items():
        teams = euro_by_gw.get(int(gw)) or {}
        if not teams or market is None or market.empty or "team" not in market.columns:
            out[gw] = market
            continue
        m = market.copy()
        mask = m["team"].isin(list(teams))
        m.loc[mask, "xpts"] = pd.to_numeric(m.loc[mask, "xpts"], errors="coerce").fillna(0.0) * mult
        out[gw] = m
    return out


def squad_exposure(squad: pd.DataFrame, euro_gw: dict[str, dict] | None) -> list[dict]:
    """Players of `squad` whose team is in a European week (one dict each)."""
    if not euro_gw or squad is None or squad.empty or "team" not in squad.columns:
        return []
    rows = []
    for _, r in squad.iterrows():
        info = euro_gw.get(r["team"])
        if not info:
            continue
        rows.append({
            "name": r.get("name"),
            "team": r["team"],
            "competition": info["competition"],
            "when": info["when"],
        })
    return rows
