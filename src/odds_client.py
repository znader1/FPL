"""The Odds API client for EPL match odds — cached, archived, fail-soft.

Free tier is 500 credits/month, so every live fetch is disk-cached
(ODDS_CACHE_TTL_S) and each fresh pull is also archived under
data/processed/odds/ as future backtest fodder. No key, no network, no
usable markets → None, and every consumer degrades to the xG-ratings path.

Aggregation: median decimal odds per outcome across bookmakers (single-book
quirks and boosted prices wash out), totals taken at each book's main line
with the most common line winning.
"""
from __future__ import annotations
import json
import os
import statistics
import time
from pathlib import Path

import requests

from src import config
from src.odds_model import implied_fixture_lambdas

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
_CACHE_DIR = Path("data/processed/odds")
_CACHE_FILE = _CACHE_DIR / "latest.json"

# FPL short/full names that don't substring-match The Odds API's naming.
_DEFAULT_ALIASES = {
    "man city": "manchester city",
    "man utd": "manchester united",
    "spurs": "tottenham hotspur",
    "nott'm forest": "nottingham forest",
    "wolves": "wolverhampton wanderers",
    "sheffield utd": "sheffield united",
}


def _now():
    return time.time()


def fetch_epl_odds(api_key=None, force=False):
    """Return the raw odds-API event list for EPL, or None.

    Serves the disk cache inside ODDS_CACHE_TTL_S; a fresh pull rewrites the
    cache and drops a timestamped archive copy.
    """
    key = api_key or os.environ.get("ODDS_API_KEY") or ""
    ttl = float(getattr(config, "ODDS_CACHE_TTL_S", 21600.0))

    if not force and _CACHE_FILE.exists():
        try:
            blob = json.loads(_CACHE_FILE.read_text())
            if _now() - float(blob.get("ts", 0)) < ttl:
                return blob.get("data")
        except Exception:
            pass

    if not key:
        return None
    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/sports/soccer_epl/odds",
            params={
                "apiKey": key,
                "regions": "eu",
                "markets": "h2h,totals",
                "oddsFormat": "decimal",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, list):
        return None

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps({"ts": _now(), "data": data}))
        stamp = time.strftime("%Y%m%d%H", time.gmtime())
        (_CACHE_DIR / f"snapshot_{stamp}.json").write_text(json.dumps(data))
    except Exception:
        pass
    return data


def aggregate_event(event):
    """One odds-API event → the fixture_odds dict odds_model consumes,
    using median odds per outcome across bookmakers. None when a needed
    market is missing."""
    home = event.get("home_team")
    away = event.get("away_team")
    h2h_prices = {home: [], "Draw": [], away: []}
    totals_by_line: dict[float, dict[str, list]] = {}

    for book in event.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") == "h2h":
                for oc in market.get("outcomes") or []:
                    name, price = oc.get("name"), oc.get("price")
                    if name in h2h_prices and price:
                        h2h_prices[name].append(float(price))
            elif market.get("key") == "totals":
                for oc in market.get("outcomes") or []:
                    point, price = oc.get("point"), oc.get("price")
                    if point is None or not price:
                        continue
                    slot = totals_by_line.setdefault(float(point), {"Over": [], "Under": []})
                    if oc.get("name") in slot:
                        slot[oc["name"]].append(float(price))

    if not all(h2h_prices.get(k) for k in (home, "Draw", away)):
        return None
    complete_lines = {ln: v for ln, v in totals_by_line.items()
                      if v["Over"] and v["Under"]}
    if not complete_lines:
        return None
    # Most-quoted line wins (the market's main line).
    line = max(complete_lines, key=lambda ln: len(complete_lines[ln]["Over"]))

    return {
        "home_team": home,
        "away_team": away,
        "h2h": [statistics.median(h2h_prices[home]),
                statistics.median(h2h_prices["Draw"]),
                statistics.median(h2h_prices[away])],
        "totals": {
            "line": line,
            "over": statistics.median(complete_lines[line]["Over"]),
            "under": statistics.median(complete_lines[line]["Under"]),
        },
    }


def _normalize(name):
    return str(name or "").strip().lower()


def match_fpl_team(odds_name, fpl_names_by_id):
    """odds-API team name → FPL team id, via exact/alias/substring match."""
    aliases = dict(_DEFAULT_ALIASES)
    aliases.update({_normalize(k): _normalize(v)
                    for k, v in (getattr(config, "ODDS_TEAM_ALIASES", {}) or {}).items()})
    target = _normalize(odds_name)
    for tid, name in fpl_names_by_id.items():
        n = _normalize(name)
        canonical = aliases.get(n, n)
        if canonical == target or n == target:
            return tid
        if canonical and (canonical in target or target in canonical):
            return tid
    return None


def odds_lambda_by_team(fpl_names_by_id, api_key=None):
    """Market-implied expected goals per FPL team id for upcoming fixtures.

    Returns {team_id: lam_for}. Empty dict on any failure — callers blend
    with the xG-ratings lambda and degrade gracefully.
    """
    events = fetch_epl_odds(api_key=api_key)
    if not events:
        return {}
    out = {}
    for event in events:
        agg = aggregate_event(event)
        if not agg:
            continue
        implied = implied_fixture_lambdas(agg)
        if not implied:
            continue
        hid = match_fpl_team(implied["home_team"], fpl_names_by_id)
        aid = match_fpl_team(implied["away_team"], fpl_names_by_id)
        # First upcoming fixture per team wins (events are date-ordered).
        if hid is not None and hid not in out:
            out[hid] = float(implied["lam_home"])
        if aid is not None and aid not in out:
            out[aid] = float(implied["lam_away"])
    return out
