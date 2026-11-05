"""Monitoring dashboard backfill: one finished report per gameweek and entry.

Collects, for the requested gameweeks:

* The Scout's articles from the Premier League content feed (src/scout_feed.py),
  matched to FPL player ids (src/scout_names.py)            -> expert_picks
* each tracked entry's picks, transfers and real score        -> entry_gw_actuals
* the app's advice rebuilt as of each gameweek
  (src/monitor_replay.py)                                     -> advice_snapshots (origin "replay")
* the assembled report (src/monitor_gw_report.py)             -> monitor_reports

Real points and minutes come from FPL's live endpoint, never from a sum of picks
and never from the snapshot table (which has no GW1 rows).

    # dry run: nothing written to the database, no service key needed
    PYTHONPATH=. python scripts/monitor_backfill.py --gws 1-10 \\
        --snapshots-csv data/replay/snapshots_2026-27.csv --out-dir /tmp/monitor-dryrun

    # real run (GitHub workflow "Monitor backfill")
    PYTHONPATH=. python scripts/monitor_backfill.py --gws 1-10 --entries 107342,5645321
Env for a real run: SUPABASE_URL, SUPABASE_SERVICE_KEY.

Advice saved before a deadline by production carries origin "live". This script
only ever writes origin "replay" rows; a live row is read and preferred, never
replaced.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from src import config, monitor_gw_report, monitor_replay, scout_feed, scout_names

logger = logging.getLogger("monitor_backfill")

FPL_API = "https://fantasy.premierleague.com/api"
USER_AGENT = "Mozilla/5.0 (compatible; monitor-backfill)"
SOURCE = "scout"
SEASON_START_LEAD_DAYS = 30   # season-start articles appear before the first deadline
PAGE_ROWS = 1000              # PostgREST's default page cap
CONFLICT_KEYS = {
    "expert_picks": "season,gw,source,series",
    "advice_snapshots": "season,gw,entry_id,kind,origin",
    "entry_gw_actuals": "season,gw,entry_id",
    "monitor_reports": "season,gw,entry_id",
}


# ---------------------------------------------------------------- pure builders

def parse_gws(spec):
    """"1-10" -> [1..10]; "3,5" -> [3, 5]; "2-3,9" -> [2, 3, 9]."""
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        lo, _, hi = part.partition("-")
        out.extend(range(int(lo), int(hi or lo) + 1))
    return out


def season_start(bootstrap):
    """ISO date a month before the season's first deadline: articles older than
    this belong to another season."""
    deadlines = [e["deadline_time"] for e in (bootstrap or {}).get("events") or [] if e.get("deadline_time")]
    first = datetime.fromisoformat(min(deadlines).replace("Z", "+00:00"))
    return (first - timedelta(days=SEASON_START_LEAD_DAYS)).date().isoformat()


def live_points_minutes(live):
    """FPL /event/{gw}/live/ payload -> ({player_id: points}, {player_id: minutes})."""
    points, minutes = {}, {}
    for e in (live or {}).get("elements") or []:
        stats = e.get("stats") or {}
        points[int(e["id"])] = int(stats.get("total_points") or 0)
        minutes[int(e["id"])] = int(stats.get("minutes") or 0)
    return points, minutes


def _plain(obj):
    """Make an engine result JSON-safe (numpy scalars, sets, NaN)."""
    def default(o):
        if isinstance(o, (set, frozenset)):
            return sorted(o)
        if hasattr(o, "item"):
            return o.item()
        return str(o)
    return json.loads(json.dumps(obj, default=default))


def expert_rows(parsed_articles, players_by_gw, teams, overrides, season, now_iso):
    """Parsed Scout articles -> expert_picks rows with every name resolved to an
    FPL player id, or listed as unmatched. `players_by_gw[gw]` are that
    gameweek's players (club as it was then); "default" is the fallback."""
    names = (overrides or {}).get("names") or {}
    rows = []
    for a in parsed_articles:
        if a.get("gw") is None or not a.get("series"):
            continue
        pool = players_by_gw.get(int(a["gw"])) or players_by_gw.get("default") or []
        by_name, players, unmatched = {}, [], []
        for p in a.get("players") or []:
            hit = scout_names.match_player(p["name_raw"], p["club_raw"], pool, teams, names)
            players.append({**p, "fpl_player_id": hit["player_id"]})
            if hit["player_id"] is None:
                unmatched.append({"name_raw": p["name_raw"], "club_raw": p["club_raw"]})
            else:
                by_name[p["name_raw"]] = hit["player_id"]
        reason = a.get("review_reason")
        if unmatched:
            reason = "; ".join(filter(None, [reason, "unmatched: " + ", ".join(u["name_raw"] for u in unmatched)]))
        rows.append({
            "season": season, "gw": int(a["gw"]), "source": SOURCE, "series": a["series"],
            "article_id": a.get("article_id"), "url": a.get("url"), "title": a.get("title"),
            "published_at": a.get("published_at"), "fetched_at": now_iso,
            "captain_player_id": by_name.get(a.get("captain")),
            "vice_player_id": by_name.get(a.get("vice")),
            "captain_stated": bool(a.get("captain_stated")),
            "captain_inferred_player_id": by_name.get(a.get("captain_inferred")),
            "players": players, "unmatched": unmatched,
            "needs_review": bool(a.get("needs_review")) or bool(unmatched),
            "review_reason": reason,
        })
    return rows


def actuals_row(entry_id, season, gw, picks_payload, transfers, history, now_iso):
    """One entry's gameweek as FPL records it. `points` is FPL's own total
    (autosubs and captain applied), not a sum of the picks."""
    eh = (picks_payload or {}).get("entry_history") or {}
    chip = (picks_payload or {}).get("active_chip")
    if chip is None:
        chip = next((c.get("name") for c in (history or {}).get("chips") or []
                     if int(c.get("event", 0) or 0) == int(gw)), None)
    made = sorted((t for t in transfers or [] if int(t.get("event", 0) or 0) == int(gw)),
                  key=lambda t: str(t.get("time") or ""))

    def tenths(value):
        return round(float(value) / 10.0, 1) if value is not None else None

    return {
        "season": season, "gw": int(gw), "entry_id": int(entry_id),
        "picks": [{k: p.get(k) for k in ("element", "position", "multiplier", "is_captain", "is_vice_captain")}
                  for p in (picks_payload or {}).get("picks") or []],
        "transfers": [{"sell_id": int(t["element_out"]), "buy_id": int(t["element_in"])} for t in made],
        "chip": chip,
        "points": eh.get("points"), "points_on_bench": eh.get("points_on_bench"),
        "transfer_cost": eh.get("event_transfers_cost"),
        "bank_m": tenths(eh.get("bank")), "value_m": tenths(eh.get("value")),
        "captured_at": now_iso,
    }


def advice_rows(entry_id, season, gw, plan, wildcard, buy_targets, code_version, now_iso):
    """Rebuilt advice -> advice_snapshots rows, always origin "replay". The buy
    list does not depend on a squad, so it is stored once under entry 0."""
    rows = []
    for kind, owner, payload in (("transfer_plan", entry_id, plan), ("wildcard_drafts", entry_id, wildcard),
                                 ("buy_targets", 0, buy_targets)):
        if payload is None:
            continue
        rows.append({"season": season, "gw": int(gw), "entry_id": int(owner), "kind": kind, "origin": "replay",
                     "model_version": code_version, "payload": _plain(payload), "captured_at": now_iso})
    return rows


def report_row(report, now_iso, code_version):
    return {"season": report["season"], "gw": int(report["gw"]), "entry_id": int(report["entry_id"]),
            "report": _plain(report), "built_at": now_iso, "code_version": code_version}


def prefer_live(replay, live_rows):
    """{(gw, kind): row} where advice saved before the deadline replaces a rebuilt one."""
    out = dict(replay)
    for row in live_rows or []:
        out[(int(row["gw"]), row["kind"])] = {"origin": row.get("origin"), "payload": row.get("payload"),
                                              "model_version": row.get("model_version")}
    return out


def players_by_gw(bootstrap, snapshots_by_gw):
    """{gw | "default": players for name matching}; club as stored for that gameweek."""
    short = {int(t["id"]): t.get("short_name") for t in bootstrap.get("teams") or []}
    base = [{"id": int(e["id"]), "first_name": e.get("first_name"), "second_name": e.get("second_name"),
             "web_name": e.get("web_name"), "team_short": short.get(int(e.get("team") or 0))}
            for e in bootstrap.get("elements") or []]
    out = {"default": base}
    for gw, snap in snapshots_by_gw.items():
        club = dict(zip(pd.to_numeric(snap["player_id"], errors="coerce").astype(int), snap["team_short"]))
        out[int(gw)] = [{**p, "team_short": club.get(p["id"], p["team_short"])} for p in base]
    return out


def bootstrap_players(bootstrap):
    short = {int(t["id"]): t.get("short_name") for t in bootstrap.get("teams") or []}
    pos = {int(t["id"]): t.get("singular_name_short") for t in bootstrap.get("element_types") or []}
    return {int(e["id"]): {"name": e.get("web_name"), "club": short.get(int(e.get("team") or 0)),
                           "pos": pos.get(int(e.get("element_type") or 0))}
            for e in bootstrap.get("elements") or []}


# ---------------------------------------------------------------- I/O shell

def _get_json(url, params=None):
    r = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    return r.json()


def fpl_get(path):
    return _get_json(f"{FPL_API}/{path}")


def feed_listing(start_date):
    """Every Scout article the feed lists for this season, deduplicated by id."""
    seen = {}
    for tag in config.SCOUT_FEED_TAGS:
        for page in range(int(config.SCOUT_FEED_MAX_PAGES)):
            body = _get_json(config.SCOUT_FEED_BASE_URL + "/", params={
                "tagNames": tag, "pageSize": int(config.SCOUT_FEED_PAGE_SIZE), "page": page})
            items = body.get("content") or []
            for it in items:
                seen[int(it["id"])] = {"id": int(it["id"]), "title": it.get("title"), "date": it.get("date")}
            if not items or all(str(it.get("date") or "") < start_date for it in items):
                break
    return list(seen.values())


def feed_article(article_id):
    return _get_json(f"{config.SCOUT_FEED_BASE_URL}/{int(article_id)}")


def _sb_headers(sb_key):
    return {"apikey": sb_key, "Authorization": f"Bearer {sb_key}", "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"}


def sb_upsert(sb_url, sb_key, table, rows):
    for i in range(0, len(rows), 200):
        r = requests.post(f"{sb_url.rstrip('/')}/rest/v1/{table}?on_conflict={CONFLICT_KEYS[table]}",
                          headers=_sb_headers(sb_key), json=rows[i:i + 200], timeout=120)
        r.raise_for_status()


def sb_select(sb_url, sb_key, table, query):
    """All rows of a PostgREST query, paged past the default row cap."""
    out, offset = [], 0
    while True:
        r = requests.get(f"{sb_url.rstrip('/')}/rest/v1/{table}?{query}&limit={PAGE_ROWS}&offset={offset}",
                         headers=_sb_headers(sb_key), timeout=120)
        r.raise_for_status()
        page = r.json()
        out.extend(page)
        if len(page) < PAGE_ROWS:
            return out
        offset += PAGE_ROWS


def load_overrides():
    path = Path(config.SCOUT_OVERRIDES_PATH)
    return json.loads(path.read_text()) if path.exists() else {}


def collect_scout(bootstrap, snapshots_by_gw, gws, season, now_iso, failures):
    """expert_picks rows for the requested gameweeks; an unreachable feed is a
    recorded failure and an empty result, never a guess."""
    overrides = load_overrides()
    try:
        listing = feed_listing(season_start(bootstrap))
    except Exception as exc:  # noqa: BLE001
        listing = []
        logger.error("Scout feed unreachable from this machine: %s", exc)
    chosen = scout_feed.pick_articles(listing, season_start(bootstrap), overrides)
    if not chosen:
        failures.append("Scout feed returned no article for this season")
        return []
    parsed = []
    for (gw, series), item in sorted(chosen.items()):
        if gw not in gws:
            continue
        try:
            parsed.append(scout_feed.parse_article(feed_article(item["id"]), overrides))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"Scout article {item['id']} (GW{gw} {series}): {exc}")
    return expert_rows(parsed, players_by_gw(bootstrap, snapshots_by_gw), bootstrap.get("teams") or [],
                       overrides, season, now_iso)


def engine_inputs(snapshots_df):
    """Local engine data for the replay, refreshed like the shadow job does."""
    from api import main as api_main
    from scripts import shadow_snapshot
    from src import fixture_difficulty, projections

    shadow_snapshot.refresh_local_data()
    history_path = projections.find_latest_gw_history()
    match_path = fixture_difficulty.find_latest_match_history()
    if not history_path or not match_path:
        raise RuntimeError("no local player history after the data refresh")
    return {"bootstrap": api_main.get_bootstrap_cached(), "fixtures": api_main.get_fixtures_cached(),
            "history_df": pd.read_csv(history_path), "match_df": pd.read_csv(match_path),
            "snapshots_df": snapshots_df}


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gws", default="1-10")
    ap.add_argument("--entries", default=",".join(str(e) for e in config.MONITOR_ENTRY_IDS))
    ap.add_argument("--out-dir", help="dry run: write JSON files here instead of the database")
    ap.add_argument("--snapshots-csv", help="read player_gw_snapshots from this export instead of the database")
    ap.add_argument("--skip-replay", action="store_true", help="do not rebuild the app's advice")
    args = ap.parse_args(argv)

    gws = parse_gws(args.gws)
    entries = [int(e) for e in str(args.entries).split(",") if e.strip()]
    dry = bool(args.out_dir)
    sb_url = os.environ.get("SUPABASE_URL")
    sb_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not dry and not (sb_url and sb_key):
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_KEY are required without --out-dir")
    now_iso = datetime.now(timezone.utc).isoformat()
    code_version = str(config.PROJ_MODEL_VERSION)
    failures = []

    bootstrap = fpl_get("bootstrap-static/")
    from src.season_history import season_label_from_bootstrap
    season = str(season_label_from_bootstrap(bootstrap))
    events = bootstrap.get("events") or []
    last_finished = max([int(e["id"]) for e in events if e.get("finished")], default=0)
    next_gw = next((int(e["id"]) for e in events if e.get("is_next")), last_finished + 1)
    gws = [g for g in gws if g <= next_gw]
    logger.info("season %s: last finished GW%s, next GW%s; building %s", season, last_finished, next_gw, gws)

    if args.snapshots_csv:
        snapshots_df = pd.read_csv(args.snapshots_csv)
    elif dry and not (sb_url and sb_key):
        logger.info("dry run without --snapshots-csv: no stored projections, the app columns will be empty")
        snapshots_df = pd.DataFrame(columns=["season", "gw", "player_id"])
    else:
        snapshots_df = pd.DataFrame(sb_select(sb_url, sb_key, "player_gw_snapshots",
                                              f"select=*&season=eq.{season}&order=gw,player_id"))
    if "season" in snapshots_df.columns:
        snapshots_df = snapshots_df[snapshots_df["season"].astype(str) == season]
    snapshots_by_gw = {int(g): df for g, df in snapshots_df.groupby(pd.to_numeric(snapshots_df["gw"]))} \
        if len(snapshots_df) else {}

    points_by_gw, minutes_by_gw = {}, {}
    for g in range(1, last_finished + 1):
        points_by_gw[g], minutes_by_gw[g] = live_points_minutes(fpl_get(f"event/{g}/live/"))

    expert = collect_scout(bootstrap, snapshots_by_gw, gws, season, now_iso, failures)
    expert_by_key = {(r["gw"], r["series"]): r for r in expert}
    logger.info("scout: %s articles, %s need review", len(expert), sum(bool(r["needs_review"]) for r in expert))

    inputs, status_dir = None, None
    if not args.skip_replay:
        try:
            inputs = engine_inputs(snapshots_df)
            status_dir = tempfile.mkdtemp(prefix="monitor-status-")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"engine data refresh failed, advice not rebuilt: {exc}")

    replayable = [g for g in gws if inputs is not None and g in snapshots_by_gw]
    buy_by_gw, parity_by_gw, status_path = {}, {}, {}
    for g in replayable:
        buy_by_gw[g] = monitor_replay.replay_buy_targets(g, inputs)
        try:
            from src import season_replay
            parity_by_gw[g] = monitor_replay.parity(season_replay.project_as_of(g, 1, inputs),
                                                    snapshots_df, g, code_version)
            status_path[g] = os.path.join(status_dir, f"status_before_gw{g}.csv")
            monitor_replay.write_status_history_as_of(snapshots_df, season, g, status_path[g])
        except Exception as exc:  # noqa: BLE001
            failures.append(f"GW{g} replay setup: {exc}")

    out = {"expert_picks": expert, "entry_gw_actuals": [], "advice_snapshots": [], "monitor_reports": []}
    for g in replayable:
        out["advice_snapshots"] += advice_rows(0, season, g, None, None, buy_by_gw[g], code_version, now_iso)

    for entry in entries:
        try:
            history = fpl_get(f"entry/{entry}/history/")
            transfers = fpl_get(f"entry/{entry}/transfers/")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"entry {entry}: {exc}")
            continue
        actuals = {}
        for g in range(1, last_finished + 1):
            try:
                actuals[g] = actuals_row(entry, season, g, fpl_get(f"entry/{entry}/event/{g}/picks/"),
                                         transfers, history, now_iso)
            except Exception as exc:  # noqa: BLE001 - an entry that joined late has no early picks
                logger.info("entry %s GW%s: no picks (%s)", entry, g, exc)
        out["entry_gw_actuals"] += list(actuals.values())
        picks_by_gw = {g: [int(p["element"]) for p in sorted(row["picks"], key=lambda p: int(p["position"]))]
                       for g, row in actuals.items()}

        advice = {}
        for g in replayable:
            state = monitor_replay.entry_state_before(g, picks_by_gw, history)
            plan = monitor_replay.replay_transfer_plan(g, state, inputs)
            if state and g in status_path:
                wildcard = monitor_replay.replay_wildcard_squads(g, state["value_m"], inputs, status_path[g])
            else:
                wildcard = {"available": False, "reason": "no squad known before this gameweek"}
            rows = advice_rows(entry, season, g, plan, wildcard, None, code_version, now_iso)
            out["advice_snapshots"] += rows
            for r in rows:
                advice[(g, r["kind"])] = r
            advice[(g, "buy_targets")] = {"origin": "replay", "model_version": code_version,
                                          "payload": _plain(buy_by_gw[g])}
        if not dry:
            advice = prefer_live(advice, sb_select(
                sb_url, sb_key, "advice_snapshots",
                f"select=gw,kind,origin,payload,model_version&season=eq.{season}&origin=eq.live"
                f"&entry_id=in.(0,{entry})"))

        data = {
            "season": season, "last_finished_gw": last_finished, "next_gw": next_gw, "code_version": code_version,
            "snapshots_by_gw": snapshots_by_gw, "points_by_gw": points_by_gw, "minutes_by_gw": minutes_by_gw,
            "bootstrap_players": bootstrap_players(bootstrap), "expert": expert_by_key,
            "actuals_by_gw": actuals, "chips": history.get("chips") or [], "advice": advice,
            "parity": parity_by_gw,
        }
        for g in gws:
            try:
                report = monitor_gw_report.build_gw_report(g, entry, data)
                out["monitor_reports"].append(report_row(report, now_iso, code_version))
                h = report["headline"]
                logger.info("entry %s GW%s: app %s  scout %s  you %s  best %s  (%s)",
                            entry, g, h["app"], h["scout"], h["you"], h["best"], h["basis"])
            except Exception as exc:  # noqa: BLE001
                failures.append(f"entry {entry} GW{g} report: {exc}")

    if dry:
        target = Path(args.out_dir)
        target.mkdir(parents=True, exist_ok=True)
        for table, rows in out.items():
            (target / f"{table}.json").write_text(json.dumps(_plain(rows), indent=1, ensure_ascii=False))
        logger.info("dry run: wrote %s", ", ".join(f"{t} ({len(r)})" for t, r in out.items()))
    else:
        for table, rows in out.items():
            if rows:
                sb_upsert(sb_url, sb_key, table, _plain(rows))
            logger.info("%s: %s rows written", table, len(rows))

    for f in failures:
        logger.error("FAILED: %s", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
