"""One gameweek's monitoring report: the app, The Scout, the owner's team and
real points, side by side. This dict is the contract the dashboard page reads.

Pure assembly: every input arrives in `data` (see `build_gw_report`), nothing
is fetched here. Three rules shape it:

* Every top-level key is always present. A part that cannot be built is
  ``{"available": False, "reason": "..."}``, so the page can say why.
* Missing is missing: no default points, no invented eleven or captain.
* Points exist only for a finished gameweek; before that, picks show with
  ``None`` points.
"""
from __future__ import annotations

import pandas as pd

from . import config, monitor_replay, monitor_scoring, monitor_xi

NO_PARITY = {"status": "no_same_version_baseline", "mae": None, "corr": None, "n": 0}
REPLAY_NOTE = ("advice rebuilt with today's engine on what was known before the deadline, "
               "at default settings (3-gameweek horizon)")
PARITY_FAIL_NOTE = ("replayed projections differ from the stored ones beyond the pass mark; stored rows "
                    "include the team knowledge discount, the replay runs without it")


def _na(reason, **extra):
    return {"available": False, "reason": reason, **extra}


def _num(value, digits=None):
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits) if digits is not None else float(value)


class _Gameweek:
    """The inputs for one gameweek plus the registry of players the report names."""

    def __init__(self, gw, data):
        self.gw = int(gw)
        self.data = data
        self.last_finished = int(data["last_finished_gw"])
        if self.gw >= int(data["next_gw"]):
            self.state = "before_deadline"
        elif self.gw <= self.last_finished:
            self.state = "finished"
        else:
            self.state = "live"
        self.finished = self.state == "finished"
        snap = (data.get("snapshots_by_gw") or {}).get(self.gw)
        self.snap = None
        if snap is not None and len(snap):
            self.snap = snap.copy()
            self.snap["player_id"] = pd.to_numeric(self.snap["player_id"], errors="coerce").astype(int)
            self.snap["xpts"] = pd.to_numeric(self.snap["model_xpts"], errors="coerce")
            self.snap = self.snap.drop_duplicates("player_id").set_index("player_id", drop=False)
        self.points = (data.get("points_by_gw") or {}).get(self.gw) or {}
        self.minutes = (data.get("minutes_by_gw") or {}).get(self.gw) or {}
        self.bootstrap = data.get("bootstrap_players") or {}
        self.players = {}

    def rows(self, ids):
        """Snapshot rows for `ids`, in that order (ids without a row are left out)."""
        ids = [int(i) for i in ids if self.snap is not None and int(i) in self.snap.index]
        return self.snap.loc[ids] if ids else pd.DataFrame(columns=["player_id", "pos", "team_short", "xpts"])

    def identity(self, pid):
        """(name, club, pos) from the gameweek's snapshot, else from bootstrap."""
        if self.snap is not None and pid in self.snap.index:
            r = self.snap.loc[pid]
            return r.get("web_name"), r.get("team_short"), r.get("pos")
        b = self.bootstrap.get(pid) or {}
        return b.get("name"), b.get("club"), b.get("pos")

    def use(self, ids):
        """Register every id so `players` describes each player the report names."""
        for pid in ids or []:
            if pid is None:
                continue
            pid = int(pid)
            if str(pid) in self.players:
                continue
            name, club, pos = self.identity(pid)
            row = self.snap.loc[pid] if self.snap is not None and pid in self.snap.index else None
            self.players[str(pid)] = {
                "name": name, "club": club, "pos": pos,
                "price_m": _num(row.get("price_m")) if row is not None else None,
                "xpts": _num(row.get("xpts"), 2) if row is not None else None,
                "points": int(self.points[pid]) if self.finished and pid in self.points else None,
                "minutes": int(self.minutes[pid]) if self.finished and pid in self.minutes else None,
            }
        return ids

    def raw_points(self, pid):
        return int(self.points[pid]) if self.finished and pid is not None and pid in self.points else None

    def score(self, ids, captain_id, vice_id):
        if not self.finished:
            return {"no_captain": None, "with_captain": None}
        return monitor_xi.score_xi(ids, captain_id, vice_id, self.points, self.minutes)


def _app_xi(g):
    if g.snap is None:
        return _na("no pre-deadline snapshot")
    pool = g.snap.rename(columns={"xpts": "value"})
    ids = monitor_xi.best_xi(pool, int(config.CHIP_MAX_PER_TEAM))
    if not ids:
        return _na("no legal eleven in the snapshot")
    rows = g.rows(ids)
    captain_id, vice_id = monitor_xi.app_captain(rows)
    scored = g.score(ids, captain_id, vice_id)
    version = None
    if "model_version" in g.snap.columns:
        known = g.snap["model_version"].dropna()
        version = str(known.iloc[0]) if len(known) else None
    g.use(ids)
    return {
        "available": True, "ids": ids, "captain_id": captain_id, "vice_id": vice_id,
        "projected": _num(rows["xpts"].sum(), 2),
        "price_m": _num(pd.to_numeric(rows["price_m"], errors="coerce").sum(), 1),
        "points_no_captain": scored["no_captain"], "points_with_captain": scored["with_captain"],
        "model_version": version,
    }


def _scout_xi(g):
    expert = g.data.get("expert") or {}
    row = expert.get((g.gw, "selection"))
    if row is None:
        if (g.gw, "season_squad") in expert:
            return _na("season squad, not an eleven")
        return _na("no Scout Selection found for this gameweek")
    ids = [int(p["fpl_player_id"]) for p in row.get("players") or [] if p.get("fpl_player_id") is not None]
    stated = bool(row.get("captain_stated"))
    captain_id = row.get("captain_player_id") if stated else None
    inferred = row.get("captain_inferred_player_id")
    scored = g.score(ids, captain_id if stated else inferred, row.get("vice_player_id") if stated else None)
    prices = [p.get("price_m") for p in row.get("players") or [] if p.get("price_m") is not None]
    g.use(ids)
    return {
        "available": True, "url": row.get("url"), "published_at": row.get("published_at"),
        "ids": ids, "unmatched": list(row.get("unmatched") or []),
        "captain_id": captain_id, "vice_id": row.get("vice_player_id") if stated else None,
        "captain_stated": stated, "captain_inferred_id": inferred if not stated else None,
        "price_m": _num(sum(prices), 1) if prices else None,
        "points_no_captain": scored["no_captain"], "points_with_captain": scored["with_captain"],
        "needs_review": bool(row.get("needs_review")),
    }


def _you(g):
    row = (g.data.get("actuals_by_gw") or {}).get(g.gw)
    if row is None:
        return _na("picks are published after the deadline" if g.state == "before_deadline"
                   else "no picks stored for this gameweek")
    picks = sorted(row.get("picks") or [], key=lambda p: int(p["position"]))
    ids = [int(p["element"]) for p in picks]
    g.use(ids)
    return {
        "available": True, "ids": ids, "xi_ids": ids[:11], "bench_ids": ids[11:],
        "captain_id": next((int(p["element"]) for p in picks if p.get("is_captain")), None),
        "vice_id": next((int(p["element"]) for p in picks if p.get("is_vice_captain")), None),
        "chip": row.get("chip"), "points": row.get("points"),
        "points_on_bench": row.get("points_on_bench"), "transfer_cost": row.get("transfer_cost"),
    }


def _best_xi(g):
    if not g.finished:
        return _na("gameweek not finished")
    rows = []
    for pid, pts in g.points.items():
        _, club, pos = g.identity(int(pid))
        if pos:
            rows.append({"player_id": int(pid), "pos": pos, "team_short": club, "value": float(pts)})
    ids = monitor_xi.best_xi(pd.DataFrame(rows, columns=["player_id", "pos", "team_short", "value"]),
                             int(config.CHIP_MAX_PER_TEAM))
    if not ids:
        return _na("no real points for this gameweek")
    g.use(ids)
    return {"available": True, "ids": ids, "points": int(sum(int(g.points[i]) for i in ids))}


def _headline(app, scout, you, best):
    basis = "with_captain" if scout.get("available") and scout.get("captain_stated") else "no_captain"
    key = f"points_{basis}"
    return {"basis": basis, "app": app.get(key), "scout": scout.get(key),
            "you": you.get("points"), "best": best.get("points")}


def _captain(g, scout, you):
    def line(pid, **extra):
        if pid is None:
            return None
        g.use([pid])
        return {"id": int(pid), "points": g.raw_points(int(pid)), **extra}

    app_for_you = None
    if you.get("available") and g.snap is not None:
        app_for_you = line(monitor_xi.app_captain(g.rows(you["xi_ids"]))[0])
    scout_line = None
    if scout.get("available"):
        scout_line = line(scout["captain_id"] if scout["captain_stated"] else scout["captain_inferred_id"],
                          stated=scout["captain_stated"])

    def best_of(ids):
        scored = [(int(g.points[i]), -int(i)) for i in ids if i in g.points]
        return line(-max(scored)[1]) if g.finished and scored else None

    return {
        "app_for_you": app_for_you, "scout": scout_line,
        "you": line(you.get("captain_id")) if you.get("available") else None,
        "best_in_squad": best_of(you["ids"]) if you.get("available") else None,
        "best_overall": best_of(list(g.points)),
    }


def _advice(g, kind):
    """(row, payload) of the stored or rebuilt advice of one kind, or (None, None)."""
    row = (g.data.get("advice") or {}).get((g.gw, kind))
    return (row, row.get("payload") or {}) if row else (None, None)


def _transfers(g, you):
    window = int(config.MONITOR_TRANSFER_VERDICT_WINDOW_GWS)
    out = {"chip_week": False, "verdict_window": window, "verdict": None}
    if you.get("available") and monitor_scoring.is_transfer_chip_week(you.get("chip")):
        return {**out, "chip_week": True, "app": _na("chip week"), "you": _na("chip week")}
    pts, last = g.data.get("points_by_gw") or {}, g.last_finished
    if you.get("available"):
        row = g.data["actuals_by_gw"][g.gw]
        moves = [{"sell_id": int(m["sell_id"]), "buy_id": int(m["buy_id"])} for m in row.get("transfers") or []]
        hits = int(row.get("transfer_cost") or 0) // int(config.TRANSFER_HIT_POINTS_STEP)
        you_line = {"available": True, "moves": moves, "hits": hits,
                    "windows": monitor_scoring.moves_windows(moves, g.gw, hits, pts, last)}
    else:
        you_line = _na(you["reason"])
    row, payload = _advice(g, "transfer_plan")
    if row is None:
        app_line = _na("no advice stored or rebuilt for this gameweek")
    elif not payload.get("available"):
        app_line = _na(payload.get("reason") or "advice unavailable")
    else:
        moves = [{"sell_id": int(m["sell_id"]), "buy_id": int(m["buy_id"])} for m in payload.get("moves") or []]
        app_line = {"available": True, "origin": row.get("origin"), "action": payload.get("action"),
                    "moves": moves, "windows": monitor_scoring.moves_windows(moves, g.gw, 0, pts, last)}
    for side in (app_line, you_line):
        for m in side.get("moves") or []:
            g.use([m["sell_id"], m["buy_id"]])
    out["verdict"] = monitor_scoring.transfers_verdict(app_line.get("windows"), you_line.get("windows"))
    return {**out, "app": app_line, "you": you_line}


def _buy_lists(g):
    pts, last = g.data.get("points_by_gw") or {}, g.last_finished
    snap_price = {} if g.snap is None else {
        int(i): _num(p) for i, p in zip(g.snap["player_id"], g.snap["price_m"])}
    row, payload = _advice(g, "buy_targets")
    if row is None or not payload.get("available"):
        app = _na((payload or {}).get("reason") or "no advice stored or rebuilt for this gameweek")
    else:
        ids = [int(i) for i in payload.get("player_ids") or []]
        app = {"available": True, "origin": row.get("origin"),
               **monitor_scoring.list_windows(g.use(ids), snap_price, g.gw, pts, last)}
    radar = (g.data.get("expert") or {}).get((g.gw, "transfer_radar"))
    if radar is None:
        scout = _na("no Scout transfer radar found for this gameweek")
    else:
        matched = [p for p in radar.get("players") or [] if p.get("fpl_player_id") is not None]
        ids = [int(p["fpl_player_id"]) for p in matched]
        prices = {int(p["fpl_player_id"]): (p["price_m"] if p.get("price_m") is not None
                                            else snap_price.get(int(p["fpl_player_id"]))) for p in matched}
        scout = {"available": True, "url": radar.get("url"), "unmatched": list(radar.get("unmatched") or []),
                 "needs_review": bool(radar.get("needs_review")),
                 **monitor_scoring.list_windows(g.use(ids), prices, g.gw, pts, last)}
    return {"app": app, "scout": scout}


def _wildcard(g, you):
    window = int(config.MONITOR_WILDCARD_WINDOW_GWS)
    data = g.data
    actuals = data.get("actuals_by_gw") or {}

    def squad(ids):
        s = monitor_scoring.squad_windows(ids, g.gw, window, data.get("snapshots_by_gw") or {},
                                          data.get("points_by_gw") or {}, data.get("minutes_by_gw") or {},
                                          g.last_finished)
        g.use(ids)
        return {"ids": [int(i) for i in ids], "points": s["points"], "played": s["played"],
                "complete": s["complete"], "no_projection_gws": s["no_projection_gws"]}

    picks_by_gw = {int(k): [int(p["element"]) for p in sorted(v.get("picks") or [], key=lambda p: int(p["position"]))]
                   for k, v in actuals.items()}
    free_hit = you.get("available") and str(you.get("chip") or "").lower() == monitor_replay.FREE_HIT
    if you.get("available") and not free_hit:
        kept_ids = you["ids"]
    else:   # a Free Hit fifteen is handed back; before the deadline his squad is the one he holds
        kept_ids = monitor_replay.permanent_squad_before(g.gw, picks_by_gw, data.get("chips") or [])
    kept = {"available": True, **squad(kept_ids)} if kept_ids else _na("squad not known for this gameweek")

    row, payload = _advice(g, "wildcard_drafts")
    if row is None or not payload.get("available"):
        app = _na((payload or {}).get("reason") or "no advice stored or rebuilt for this gameweek")
    else:
        app = {"available": True, "origin": row.get("origin"),
               "headline_preset": config.MONITOR_WILDCARD_HEADLINE_PRESET,
               "presets": {name: (squad(ids) if ids else None)
                           for name, ids in (payload.get("presets") or {}).items()},
               "notes": list(payload.get("notes") or [])}

    expert = data.get("expert") or {}
    article = expert.get((g.gw, "wildcard")) or expert.get((g.gw, "season_squad"))
    if article is None:
        scout = _na("no Scout wildcard squad this gameweek")
    elif article.get("needs_review"):
        scout = _na("squad article needs review", url=article.get("url"))
    else:
        ids = [int(p["fpl_player_id"]) for p in article.get("players") or [] if p.get("fpl_player_id") is not None]
        scout = {"available": True, "url": article.get("url"), **squad(ids)}

    played = [x for x in range(g.gw, g.gw + window) if x <= g.last_finished and x in actuals]
    actual = {"points": int(sum(int(actuals[x].get("points") or 0) for x in played)), "played": len(played)}

    verdict = None
    head = (app.get("presets") or {}).get(config.MONITOR_WILDCARD_HEADLINE_PRESET) if app.get("available") else None
    if head and kept.get("available") and head["complete"] and kept["complete"]:
        verdict = "level" if head["points"] == kept["points"] else ("app" if head["points"] > kept["points"] else "kept")
    return {"window": window, "kept": kept, "app": app, "scout": scout, "actual": actual, "verdict": verdict}


def _replay(g):
    parity = (g.data.get("parity") or {}).get(g.gw) or dict(NO_PARITY)
    rows = [r for (gw, _), r in (g.data.get("advice") or {}).items() if gw == g.gw]
    notes = []
    if any(r.get("origin") == "replay" for r in rows):
        notes.append(REPLAY_NOTE)
    _, wildcard = _advice(g, "wildcard_drafts")
    notes += list((wildcard or {}).get("notes") or [])
    if parity.get("status") == "fail":
        notes.append(PARITY_FAIL_NOTE)
    _, plan = _advice(g, "transfer_plan")
    return {"parity": parity, "dropped_squad_ids": [int(i) for i in (plan or {}).get("dropped_squad_ids") or []],
            "notes": notes}


def build_gw_report(gw, entry_id, data):
    """Assemble the report for one gameweek and one entry.

    `data` (plain Python and DataFrames, no network):
      season, last_finished_gw, next_gw, code_version,
      snapshots_by_gw   {gw: player_gw_snapshots rows} (absent for GW1),
      points_by_gw, minutes_by_gw   {gw: {player_id: value}} from FPL's live endpoint,
      bootstrap_players {player_id: {name, club, pos}} (identity when a gameweek has no snapshot),
      expert            {(gw, series): expert_picks row with fpl_player_id on each player},
      actuals_by_gw     {gw: entry_gw_actuals row for this entry},
      chips             this entry's chips from FPL history,
      advice            {(gw, kind): advice_snapshots row}, kind in transfer_plan /
                        wildcard_drafts / buy_targets (a live row preferred over a replayed one),
      parity            {gw: parity dict}.
    """
    g = _Gameweek(gw, data)
    app, scout, you, best = _app_xi(g), _scout_xi(g), _you(g), _best_xi(g)
    report = {
        "season": data["season"], "gw": g.gw, "entry_id": int(entry_id), "state": g.state,
        "app_xi": app, "scout_xi": scout, "you": you, "best_xi": best,
        "headline": _headline(app, scout, you, best),
        "captain": _captain(g, scout, you),
        "transfers": _transfers(g, you),
        "buy_lists": _buy_lists(g),
        "wildcard": _wildcard(g, you),
        "replay": _replay(g),
    }
    report["players"] = g.players
    return report
