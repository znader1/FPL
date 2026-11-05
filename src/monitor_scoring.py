"""Scoring over gameweek windows for the monitoring dashboard.

A transfer, a buy list and a wildcard squad all pay off after the week they are
made for, so each is scored over the gameweeks that follow, starting with its
own. Only finished gameweeks count; an unfinished window reports how much of it
has been played and gives no verdict.

`points_by_gw` / `minutes_by_gw`: {gameweek: {player_id: value}} of real FPL
points and minutes.
"""
from __future__ import annotations

import pandas as pd

from . import config, monitor_xi

TRANSFER_CHIPS = ("freehit", "wildcard")  # FPL's chip names: weeks where transfers are not transfers


def is_transfer_chip_week(chip):
    return str(chip or "").lower() in TRANSFER_CHIPS


def _finished_gws(gw, window, last_finished_gw):
    return [g for g in range(int(gw), int(gw) + int(window)) if g <= int(last_finished_gw)]


def window_points(player_id, gw, window, points_by_gw, last_finished_gw):
    """A player's real points over `window` gameweeks from `gw`. A player absent
    from a finished gameweek (no fixture, left the game) counts 0 for it."""
    gws = _finished_gws(gw, window, last_finished_gw)
    pts = sum(int((points_by_gw.get(g) or {}).get(int(player_id), 0) or 0) for g in gws)
    return {"points": int(pts), "played": len(gws), "complete": len(gws) == int(window)}


def moves_windows(moves, gw, hits, points_by_gw, last_finished_gw, windows=None):
    """Gain of a set of transfers made for `gw`: points of each player bought
    minus points of the player sold, minus the hit cost. Raw points whether or
    not the player would have started. No moves = 0 (the "did nothing" line)."""
    windows = windows or config.MONITOR_WINDOWS_GWS
    cost = int(config.TRANSFER_HIT_POINTS_STEP) * int(hits or 0)
    out = {}
    for w in windows:
        gain, played = -cost, len(_finished_gws(gw, w, last_finished_gw))
        for m in moves or []:
            buy = window_points(m["buy_id"], gw, w, points_by_gw, last_finished_gw)
            sell = window_points(m["sell_id"], gw, w, points_by_gw, last_finished_gw)
            gain += buy["points"] - sell["points"]
        out[str(w)] = {"gain": int(gain), "played": played, "complete": played == int(w)}
    return out


def transfers_verdict(app_windows, you_windows):
    """Who did better on the verdict window: "app", "you", "level"; None while
    that window is unfinished or the app's line is unavailable."""
    key = str(config.MONITOR_TRANSFER_VERDICT_WINDOW_GWS)
    app, you = (app_windows or {}).get(key), (you_windows or {}).get(key)
    if not app or not you or not app.get("complete") or not you.get("complete"):
        return None
    if app["gain"] == you["gain"]:
        return "level"
    return "app" if app["gain"] > you["gain"] else "you"


def list_windows(player_ids, prices_m, gw, points_by_gw, last_finished_gw, windows=None):
    """A buy list scored as plain points per listed player, with the average per
    player and the average points per £m (players without a price are left out
    of the per-£m average only)."""
    windows = windows or config.MONITOR_WINDOWS_GWS
    players = []
    for pid in player_ids or []:
        price = (prices_m or {}).get(int(pid))
        players.append({
            "id": int(pid),
            "price_m": float(price) if price is not None and not pd.isna(price) else None,
            "windows": {str(w): window_points(pid, gw, w, points_by_gw, last_finished_gw) for w in windows},
        })
    avg, avg_per_m = {}, {}
    for w in windows:
        k = str(w)
        pts = [p["windows"][k]["points"] for p in players]
        per_m = [p["windows"][k]["points"] / p["price_m"] for p in players if p["price_m"]]
        avg[k] = (sum(pts) / len(pts)) if pts else None
        avg_per_m[k] = (sum(per_m) / len(per_m)) if per_m else None
    return {"players": players, "avg": avg, "avg_per_m": avg_per_m}


def squad_windows(squad_ids, gw, window, snapshots_by_gw, points_by_gw, minutes_by_gw, last_finished_gw):
    """Real points of a frozen squad over a window. Each finished gameweek the
    squad fields the eleven and captain that gameweek's stored pre-deadline
    projection would pick (no hindsight), scored on real points.

    `snapshots_by_gw[g]`: that gameweek's snapshot rows (player_id, web_name,
    pos, team_short, price_m, model_xpts). A squad player with no row that
    gameweek cannot be fielded and is named in `absent`. A gameweek with no
    snapshot rows at all (GW1) cannot have a line-up picked: it is skipped,
    not counted as played, and named in `no_projection_gws`."""
    squad = [int(i) for i in squad_ids or []]
    by_gw, no_projection, total = {}, [], 0
    for g in _finished_gws(gw, window, last_finished_gw):
        snap = snapshots_by_gw.get(g)
        if snap is None or len(snap) == 0:
            no_projection.append(g)
            continue
        rows = snap[pd.to_numeric(snap["player_id"], errors="coerce").isin(squad)].copy()
        rows["player_id"] = rows["player_id"].astype(int)
        rows["xpts"] = pd.to_numeric(rows["model_xpts"], errors="coerce").fillna(0.0)
        present = set(rows["player_id"])
        lineup = monitor_xi.pick_lineup(rows) if len(rows) else {"xi": [], "captain_id": None, "vice_id": None}
        scored = monitor_xi.score_xi(lineup["xi"], lineup["captain_id"], lineup["vice_id"],
                                     points_by_gw.get(g) or {}, minutes_by_gw.get(g) or {})
        pts = scored["with_captain"] if scored["with_captain"] is not None else scored["no_captain"]
        by_gw[g] = {"xi": lineup["xi"], "captain_id": lineup["captain_id"], "points": int(pts),
                    "absent": [i for i in squad if i not in present]}
        total += int(pts)
    return {"points": int(total), "played": len(by_gw), "complete": len(by_gw) == int(window),
            "by_gw": by_gw, "no_projection_gws": no_projection}
