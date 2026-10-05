"""
Data freshness: age of every source the engine reads, against a threshold.

Two layers so the judgement is testable without a filesystem:

* ``collect_inputs`` reads the real files (refresh receipt, newest history
  CSVs, odds cache, knowledge files, news corpus) and returns plain dicts.
* ``build_data_status`` turns those dicts plus the bootstrap into the payload
  ``GET /admin/data-status`` serves.

Hard sources decide ``ok``: the refresh receipt, ``player_gw_history`` (the
ppg/form baseline) and ``player_match_history`` (the xG model). When one of
them lags a finished gameweek the recommendations are built on last week's
numbers, which is exactly the "fresh or flagged" failure. Everything else
(odds, knowledge files, European calendar, news) degrades gracefully in the
engine, so it only warns.
"""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import config, european, fixture_difficulty, projections, refresh_status

logger = logging.getLogger(__name__)

_ODDS_CACHE_FILE = Path("data/processed/odds/latest.json")
_HARD_SOURCES = ("refresh", "player_gw_history", "match_history")


# --- helpers -----------------------------------------------------------------

def _utc_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_iso(value):
    """Parse the ISO strings this codebase writes; None on anything else."""
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _age_days(now, dt):
    return int((now - dt).total_seconds() // 86400)


def _finished_gw(bootstrap):
    """Highest gameweek FPL has finished *and* data-checked (points final)."""
    gws = [
        int(e.get("id") or 0)
        for e in (bootstrap or {}).get("events", [])
        if e.get("finished") and e.get("data_checked")
    ]
    return max(gws) if gws else 0


def _next_gw(bootstrap):
    for e in (bootstrap or {}).get("events", []):
        if e.get("is_next"):
            return int(e.get("id") or 0) or None
    return None


# --- collector ----------------------------------------------------------------

def collect_inputs(bootstrap, team_ratings, now=None):
    """Read every source from disk. Each entry is a plain dict or None."""
    now = now or datetime.now(timezone.utc)
    return {
        "now": now,
        "bootstrap": bootstrap,
        "refresh_receipt": refresh_status.read_refresh_status(),
        "player_gw_history": _player_gw_history_info(now),
        "match_history": _match_history_info(),
        "team_ratings": team_ratings or {},
        "odds_cache": _odds_cache_blob(),
        "knowledge_discount": fixture_difficulty.load_knowledge_discount(),
        "player_knowledge": _player_knowledge_blob(),
        "european_calendar": european.load_european_calendar(),
        "news_latest_at": _news_latest_at(),
    }


def _player_gw_history_info(now):
    path = projections.find_latest_gw_history()
    if not path:
        return None
    m = re.search(r"player_gw_history_(\d+)", Path(path).name)
    try:
        modified_at = datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc)
    except OSError:
        modified_at = None
    return {
        "path": path,
        "max_gw": int(m.group(1)) if m else None,
        "modified_at": modified_at,
    }


def _match_history_info():
    path = fixture_difficulty.find_latest_match_history()
    if not path:
        return None
    try:
        events = pd.to_numeric(pd.read_csv(path, usecols=["event"])["event"], errors="coerce").dropna()
    except Exception as exc:  # noqa: BLE001 - unreadable file reads as "no events"
        logger.warning("data_status: could not read %s: %s", path, exc)
        return {"path": path, "max_event": None, "rows": 0}
    return {
        "path": path,
        "max_event": int(events.max()) if len(events) else None,
        "rows": int(len(events)),
    }


def _odds_cache_blob():
    if not _ODDS_CACHE_FILE.exists():
        return None
    try:
        blob = json.loads(_ODDS_CACHE_FILE.read_text())
    except Exception:  # noqa: BLE001 - corrupt cache is "no cache"
        return None
    return blob if isinstance(blob, dict) else None


def _player_knowledge_blob():
    fp = Path(config.PLAYER_KNOWLEDGE_PATH)
    if not fp.exists():
        return {}
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _news_latest_at():
    base = Path(config.NEWS_KB_DIR)
    if not base.is_dir():
        return None
    try:
        files = [p for p in base.iterdir() if p.is_file()]
        if not files:
            return None
        newest = max(p.stat().st_mtime for p in files)
    except OSError:
        return None
    return datetime.fromtimestamp(newest, tz=timezone.utc)


# --- builder -----------------------------------------------------------------

def build_data_status(now, bootstrap, refresh_receipt, player_gw_history, match_history,
                      team_ratings, odds_cache, knowledge_discount, player_knowledge,
                      european_calendar, news_latest_at):
    finished_gw = _finished_gw(bootstrap)
    sources = {
        "refresh": _refresh_source(now, refresh_receipt),
        "player_gw_history": _gw_lag_source(
            finished_gw, player_gw_history, key="max_gw"),
        "match_history": _gw_lag_source(
            finished_gw, match_history, key="max_event"),
        "team_ratings": _ratings_source(finished_gw, team_ratings),
        "odds": _odds_source(now, odds_cache),
        "knowledge_discount": _dated_source(
            now, knowledge_discount, int(config.DATA_STATUS_KNOWLEDGE_DISCOUNT_STALE_DAYS)),
        "player_knowledge": _dated_source(
            now, player_knowledge, int(config.PLAYER_KNOWLEDGE_STALE_DAYS)),
        "european_calendar": _calendar_source(now, european_calendar),
        "news": _news_source(now, news_latest_at),
    }
    stale = [name for name in _HARD_SOURCES if sources[name]["status"] != "ok"]
    warnings = [
        name for name, src in sources.items()
        if name not in _HARD_SOURCES and src["status"] != "ok"
    ]
    return {
        "ok": not stale,
        "checked_at_utc": _utc_iso(now),
        "finished_gw": finished_gw,
        "next_gw": _next_gw(bootstrap),
        "stale": stale,
        "warnings": warnings,
        "sources": sources,
    }


def _refresh_source(now, receipt):
    receipt = receipt or {}
    max_age_h = float(config.DATA_STATUS_REFRESH_MAX_AGE_H)
    if receipt.get("ok") is False:
        return {
            "status": "failed",
            "error": str(receipt.get("error") or ""),
            "failed_at_utc": receipt.get("failed_at_utc"),
            "max_age_hours": max_age_h,
        }
    at = _parse_iso(receipt.get("cache_refreshed_at_utc"))
    if at is None:
        return {"status": "missing", "max_age_hours": max_age_h}
    age_h = (now - at).total_seconds() / 3600.0
    return {
        "status": "ok" if age_h <= max_age_h else "stale",
        "refreshed_at_utc": receipt.get("cache_refreshed_at_utc"),
        "age_hours": round(age_h, 2),
        "max_age_hours": max_age_h,
    }


def _gw_lag_source(finished_gw, info, key):
    if not info or info.get(key) is None:
        # Pre-season nothing can lag and nothing has been written yet.
        if finished_gw == 0:
            return {"status": "ok", "max_gw": None, "finished_gw": 0, "lag_gws": 0,
                    "note": "no finished gameweek yet"}
        return {"status": "missing", "max_gw": None, "finished_gw": finished_gw,
                "lag_gws": finished_gw}
    max_gw = int(info[key])
    lag = max(0, finished_gw - max_gw)
    out = {
        "status": "ok" if lag == 0 else "stale",
        "path": info.get("path"),
        "max_gw": max_gw,
        "finished_gw": finished_gw,
        "lag_gws": lag,
    }
    if info.get("rows") is not None:
        out["rows"] = info["rows"]
    if info.get("modified_at") is not None:
        out["modified_at_utc"] = _utc_iso(info["modified_at"])
    return out


def _ratings_source(finished_gw, ratings):
    by_source = {}
    live_teams = 0
    min_samples = None
    # resolve_team_ratings keeps a "_league" scalar beside the per-team dicts.
    teams = [r for r in (ratings or {}).values() if isinstance(r, dict)]
    for r in teams:
        src = str(r.get("source") or "unknown")
        by_source[src] = by_source.get(src, 0) + 1
        samples = float(r.get("samples") or 0.0)
        if samples > 0:
            live_teams += 1
        min_samples = samples if min_samples is None else min(min_samples, samples)
    out = {
        "status": "ok",
        "teams": len(teams),
        "by_source": by_source,
        "live_teams": live_teams,
        "min_samples": min_samples,
        "finished_gw": finished_gw,
    }
    if not teams:
        out["status"] = "missing"
    elif finished_gw >= 1 and live_teams == 0:
        out["status"] = "stale"
        out["note"] = "every team is still on the carryover seed although gameweeks have finished"
    return out


def _odds_source(now, blob):
    ttl_s = float(config.ODDS_CACHE_TTL_S)
    if not blob or blob.get("ts") is None:
        return {"status": "missing", "ttl_hours": round(ttl_s / 3600.0, 2)}
    try:
        age_s = now.timestamp() - float(blob["ts"])
    except (TypeError, ValueError):
        return {"status": "missing", "ttl_hours": round(ttl_s / 3600.0, 2)}
    return {
        "status": "ok" if age_s <= ttl_s else "stale",
        "age_hours": round(age_s / 3600.0, 2),
        "ttl_hours": round(ttl_s / 3600.0, 2),
    }


def _dated_source(now, blob, stale_days):
    as_of = _parse_date((blob or {}).get("as_of"))
    if as_of is None:
        return {"status": "missing", "stale_days": stale_days}
    age = _age_days(now, as_of)
    return {
        "status": "ok" if age <= stale_days else "stale",
        "as_of": (blob or {}).get("as_of"),
        "age_days": age,
        "stale_days": stale_days,
    }


def _calendar_source(now, calendar):
    calendar = calendar or {}
    teams = calendar.get("teams") or {}
    out = {
        "status": "ok",
        "as_of": calendar.get("as_of"),
        "teams": len(teams) if isinstance(teams, dict) else 0,
    }
    if not calendar:
        out["status"] = "missing"
    elif out["teams"] == 0:
        out["status"] = "stale"
        out["note"] = "teams map is empty — the European-fixture signal is off"
    return out


def _news_source(now, latest_at):
    stale_days = int(config.DATA_STATUS_NEWS_STALE_DAYS)
    if latest_at is None:
        return {"status": "missing", "stale_days": stale_days}
    age = _age_days(now, latest_at)
    return {
        "status": "ok" if age <= stale_days else "stale",
        "latest_at_utc": _utc_iso(latest_at),
        "age_days": age,
        "stale_days": stale_days,
    }
