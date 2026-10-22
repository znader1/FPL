"""
Engine-blind narrative facts for wildcard picks (spec 4.9).

Nothing here touches a score. The explainer may cite these numbers and
nothing else: record against the next opponent, a milestone within reach,
and the current streak of returns. Samples are tiny by nature, so every
fact carries its sample size.
"""
from __future__ import annotations

import pandas as pd

MILESTONE_STEP = 50
MILESTONE_WITHIN = 5
RETURN_POINTS = 4
MILESTONE_STATS = [("goals", "goals_scored"), ("assists", "assists"), ("clean_sheets", "clean_sheets")]


def _opponent_map(fixtures_df):
    """{fixture_id: (team_h, team_a)}"""
    if fixtures_df is None or fixtures_df.empty or not {"id", "team_h", "team_a"} <= set(fixtures_df.columns):
        return {}
    out = {}
    for fid, h, a in zip(fixtures_df["id"], fixtures_df["team_h"], fixtures_df["team_a"]):
        try:
            out[int(fid)] = (int(h), int(a))
        except (TypeError, ValueError):
            continue
    return out


def _milestone(row):
    if row is None:
        return None
    for stat, col in MILESTONE_STATS:
        cur = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]
        if pd.isna(cur):
            continue
        cur = int(cur)
        if cur <= 0:
            continue
        target = ((cur // MILESTONE_STEP) + 1) * MILESTONE_STEP
        if 0 < target - cur <= MILESTONE_WITHIN:
            return {"stat": stat, "current": cur, "target": target}
    return None


def for_players(player_ids, next_opponent, match_df, fixtures_df, elements_df):
    """
    → {player_id: {"vs_opponent": {games, goals, assists, points} | None,
                   "milestone": {stat, current, target} | None,
                   "streak": int}}
    next_opponent: {player_id: opponent team id this GW}.
    match_df: player_match_history rows (element, team_id, fixture, event,
    total_points, goals_scored?, assists?). fixtures_df: id/team_h/team_a.
    elements_df: bootstrap elements with goals_scored/assists/clean_sheets.
    """
    fx = _opponent_map(fixtures_df)
    el = {}
    if elements_df is not None and not elements_df.empty and "id" in elements_df.columns:
        el = {int(r["id"]): r for _, r in elements_df.iterrows()}
    have_matches = match_df is not None and not match_df.empty and {"element", "event", "total_points"} <= set(match_df.columns)

    out = {}
    for pid in player_ids:
        pid = int(pid)
        vs = None
        streak = 0
        if have_matches:
            g = match_df[pd.to_numeric(match_df["element"], errors="coerce") == pid].copy()
            g["event"] = pd.to_numeric(g["event"], errors="coerce")
            g = g.sort_values("event")
            pts = pd.to_numeric(g["total_points"], errors="coerce").fillna(0.0).tolist()
            for p in reversed(pts):
                if p >= RETURN_POINTS:
                    streak += 1
                else:
                    break
            opp = next_opponent.get(pid) if next_opponent else None
            if opp is not None and "fixture" in g.columns and "team_id" in g.columns:
                def _opp_of(row):
                    if pd.isna(row["fixture"]) or pd.isna(row["team_id"]):
                        return None
                    pair = fx.get(int(row["fixture"]))
                    if not pair:
                        return None
                    own = int(row["team_id"])
                    return pair[1] if pair[0] == own else pair[0] if pair[1] == own else None
                g["_opp"] = g.apply(_opp_of, axis=1)
                meet = g[g["_opp"] == int(opp)]
                if len(meet):
                    vs = {
                        "games": int(len(meet)),
                        "goals": int(pd.to_numeric(meet.get("goals_scored"), errors="coerce").fillna(0).sum()) if "goals_scored" in meet.columns else 0,
                        "assists": int(pd.to_numeric(meet.get("assists"), errors="coerce").fillna(0).sum()) if "assists" in meet.columns else 0,
                        "points": int(pd.to_numeric(meet["total_points"], errors="coerce").fillna(0).sum()),
                    }
        out[pid] = {"vs_opponent": vs, "milestone": _milestone(el.get(pid)), "streak": int(streak)}
    return out
