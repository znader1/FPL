"""Elevens for the monitoring dashboard: the best legal eleven from a pool, the
line-up a squad would field, and how an eleven scored.

`best_xi` is exact. The dashboard compares totals that can sit one point apart
(GW9 2026-27: the last slot of the app's eleven was decided by 0.002 projected
points and swung 8 real ones), so a greedy pick that repairs the club cap
afterwards is not good enough.
"""
from __future__ import annotations

import pandas as pd

from . import captain_advisor
from .optimizer import VALID_FORMATIONS

POSITIONS = ("GKP", "DEF", "MID", "FWD")
_EPS = 1e-9


def _by_position(pool):
    """{pos: [(value, player_id, club)]}, best first, ties by lower id."""
    df = pool[["player_id", "pos", "team_short", "value"]].copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value", "player_id"])
    out = {p: [] for p in POSITIONS}
    for pid, pos, club, value in zip(df["player_id"], df["pos"], df["team_short"], df["value"]):
        if pos in out:
            out[pos].append((float(value), int(pid), str(club)))
    for pos in out:
        out[pos].sort(key=lambda r: (-r[0], r[1]))
    return out


def best_xi(pool, max_per_club):
    """Ids of the legal eleven with the highest summed `value` (1 GKP and a
    formation from VALID_FORMATIONS; at most `max_per_club` from one club, None
    = no cap). Exact: depth-first over positions with an optimistic bound.
    Returns [] when no legal eleven exists. Ordered GKP, DEF, MID, FWD."""
    by_pos = _by_position(pool)
    best = {"total": None, "ids": []}

    def search(needs, pos_i, start, left, total, picked, clubs, tail_bound):
        # tail_bound[pos_i]: the most the positions after this one can add, cap ignored.
        if left == 0:
            pos_i += 1
            if pos_i == len(POSITIONS):
                if best["total"] is None or total > best["total"] + _EPS:
                    best["total"], best["ids"] = total, list(picked)
                return
            start, left = 0, needs[pos_i]
            if left == 0:
                return search(needs, pos_i, 0, 0, total, picked, clubs, tail_bound)
        rows = by_pos[POSITIONS[pos_i]]
        for i in range(start, len(rows) - left + 1):
            value, pid, club = rows[i]
            # Rows are sorted, so the best this branch can do is the next `left` rows.
            bound = total + sum(r[0] for r in rows[i:i + left]) + tail_bound[pos_i]
            if best["total"] is not None and bound <= best["total"] + _EPS:
                break
            if max_per_club is not None and clubs.get(club, 0) >= max_per_club:
                continue
            clubs[club] = clubs.get(club, 0) + 1
            picked.append(pid)
            search(needs, pos_i, i + 1, left - 1, total + value, picked, clubs, tail_bound)
            picked.pop()
            clubs[club] -= 1

    for d, m, f in VALID_FORMATIONS:
        needs = [1, d, m, f]
        if any(len(by_pos[p]) < n for p, n in zip(POSITIONS, needs)):
            continue
        tops = [sum(r[0] for r in by_pos[p][:n]) for p, n in zip(POSITIONS, needs)]
        tail_bound = [sum(tops[i + 1:]) for i in range(len(POSITIONS))]
        search(needs, 0, 0, needs[0], 0.0, [], {}, tail_bound)
    return best["ids"]


def app_captain(xi):
    """(captain_id, vice_id) by the product's own captain rule
    (captain_advisor.recommend_captain), which is not simply the highest
    projection. `xi` columns: player_id, pos, price_m, xpts, [web_name, team_short]."""
    if xi is None or len(xi) == 0:
        return (None, None)
    df = pd.DataFrame({
        "player_id": pd.to_numeric(xi["player_id"], errors="coerce").astype(int),
        "name": xi["web_name"].astype(str) if "web_name" in xi.columns else xi["player_id"].astype(str),
        "pos": xi["pos"].astype(str),
        "team": xi["team_short"].astype(str) if "team_short" in xi.columns else "",
        "price_m": pd.to_numeric(xi.get("price_m", 0.0), errors="coerce").fillna(0.0),
        "xpts": pd.to_numeric(xi["xpts"], errors="coerce").fillna(0.0),
    })
    recs = captain_advisor.recommend_captain(df, top_n=2)
    ids = [int(r.player_id) for r in recs]
    return (ids[0] if ids else None, ids[1] if len(ids) > 1 else None)


def pick_lineup(squad):
    """The eleven a squad fields on its projections → {xi, bench, captain_id, vice_id}.
    `squad` columns: player_id, pos, team_short, xpts, [price_m, web_name].
    A squad that cannot fill a legal formation fields its best eleven by projection."""
    df = squad.copy()
    df["value"] = pd.to_numeric(df["xpts"], errors="coerce").fillna(0.0)
    xi_ids = best_xi(df, None)
    if not xi_ids:
        xi_ids = [int(i) for i in df.sort_values(["value", "player_id"], ascending=[False, True])
                  ["player_id"].head(11)]
    chosen = set(xi_ids)
    rest = df[~df["player_id"].astype(int).isin(chosen)].sort_values(
        ["value", "player_id"], ascending=[False, True])
    captain_id, vice_id = app_captain(df[df["player_id"].astype(int).isin(chosen)])
    return {"xi": xi_ids, "bench": [int(i) for i in rest["player_id"]],
            "captain_id": captain_id, "vice_id": vice_id}


def score_xi(xi_ids, captain_id, vice_id, points, minutes):
    """Real points of an eleven → {no_captain, with_captain, captain_used, missing}.

    The captain counts twice; if he played no minutes the vice-captain does; if
    neither played, nobody. `with_captain` is None when no captain was given.
    A player absent from `points` adds 0 and is named in `missing`, so a gap in
    the data is visible rather than read as a blank."""
    ids = [int(i) for i in xi_ids]
    missing = [i for i in ids if i not in points]
    base = int(sum(int(points.get(i, 0)) for i in ids))
    if captain_id is None:
        return {"no_captain": base, "with_captain": None, "captain_used": None, "missing": missing}
    used = None
    for candidate in (captain_id, vice_id):
        if candidate is not None and int(minutes.get(int(candidate), 0) or 0) > 0:
            used = int(candidate)
            break
    total = base + (int(points.get(used, 0)) if used is not None else 0)
    return {"no_captain": base, "with_captain": total, "captain_used": used, "missing": missing}
