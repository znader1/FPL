"""As-of-GW engine inputs for replaying this season's finished gameweeks.

The live projection code is replayed for a past target GW ``t`` from:

* the stored pre-deadline snapshot row for ``t`` (price, status, chance,
  FPL ep_next, ownership — captured before ``t``'s deadline);
* the per-GW player history, capped at GWs ``< t`` (points, minutes, starts);
* the per-match history, capped at events ``< t`` (per-90 xG components);
* static bootstrap fields (team, position, set-piece orders).

Nothing from GW ``t`` or later reaches the inputs except that snapshot row.
Players without a snapshot row for ``t`` are dropped and reported, never
filled with defaults.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import transforms

FORM_WINDOW_GWS = 4
PER90_COLUMNS = {
    "expected_goals_per_90": "expected_goals",
    "expected_assists_per_90": "expected_assists",
    "expected_goals_conceded_per_90": "expected_goals_conceded",
    "saves_per_90": "saves",
}


def cap_match_history(match_df, target_gw):
    if match_df is None or match_df.empty:
        return pd.DataFrame() if match_df is None else match_df.iloc[0:0].copy()
    ev = pd.to_numeric(match_df["event"], errors="coerce")
    return match_df[ev < int(target_gw)].copy()


def _as_of_fixtures(fixtures, target_gw):
    fx = pd.DataFrame(fixtures).copy()
    if fx.empty:
        return fx
    ev = pd.to_numeric(fx["event"], errors="coerce")
    future = ev >= int(target_gw)
    for col in ("team_h_score", "team_a_score"):
        if col in fx.columns:
            fx[col] = fx[col].astype("object")
            fx.loc[future, col] = None
    for col in ("finished", "finished_provisional", "started"):
        if col in fx.columns:
            fx.loc[future, col] = False
    return fx


def _history_aggregates(history_capped):
    h = history_capped.copy()
    for col in ("gw_total_points", "gw_minutes", "gw_starts", "gw_fixture_count"):
        h[col] = pd.to_numeric(h.get(col), errors="coerce").fillna(0.0)
    h = h.sort_values(["player_id", "gw"])
    rows = {}
    for pid, g in h.groupby("player_id"):
        apps = int((g["gw_minutes"] > 0).sum())
        total = float(g["gw_total_points"].sum())
        played = g[g["gw_fixture_count"] > 0].tail(FORM_WINDOW_GWS)
        rows[int(pid)] = {
            "total_points": total,
            "minutes": float(g["gw_minutes"].sum()),
            "starts": float(g["gw_starts"].sum()),
            "points_per_game": total / apps if apps else 0.0,
            "form": float(played["gw_total_points"].mean()) if len(played) else 0.0,
            "event_points": float(g["gw_total_points"].iloc[-1]),
        }
    return rows


def _per90(match_capped):
    if match_capped is None or match_capped.empty:
        return {}
    m = match_capped.copy()
    m["minutes"] = pd.to_numeric(m["minutes"], errors="coerce").fillna(0.0)
    out = {}
    for el, g in m.groupby("element"):
        mins = float(g["minutes"].sum())
        vals = {}
        for col, src_col in PER90_COLUMNS.items():
            if mins > 0 and src_col in g.columns:
                vals[col] = float(pd.to_numeric(g[src_col], errors="coerce").fillna(0.0).sum()) * 90.0 / mins
            else:
                vals[col] = np.nan
        out[int(el)] = vals
    return out


def build_live_engine_inputs(target_gw, horizon, bootstrap, fixtures, history_df, snapshots_df,
                             match_df=None):
    """→ (elements, fixtures_as_of, teams_short_map, history_capped, dropped_ids)."""
    target_gw = int(target_gw)
    elements, teams, _ = transforms.tables_from_bootstrap(bootstrap)
    teams_short_map = teams.set_index("id")["short_name"].to_dict()

    snaps = snapshots_df[pd.to_numeric(snapshots_df["gw"], errors="coerce") == target_gw]
    snaps = snaps.drop_duplicates("player_id", keep="last").set_index("player_id")
    ids = pd.to_numeric(elements["id"], errors="coerce").astype(int)
    keep = ids.isin(snaps.index)
    dropped_ids = sorted(int(i) for i in ids[~keep])
    elements = elements[keep].copy().reset_index(drop=True)
    pid = elements["id"].astype(int)

    history_capped = history_df[pd.to_numeric(history_df["gw"], errors="coerce") < target_gw].copy()
    agg = _history_aggregates(history_capped)
    for col in ("total_points", "minutes", "starts", "points_per_game", "form", "event_points"):
        elements[col] = pid.map(lambda p, c=col: agg.get(p, {}).get(c, 0.0)).astype(float)

    snap = snaps.reindex(pid.values)
    chance = pd.to_numeric(snap["chance"], errors="coerce").values
    elements["now_cost"] = np.round(pd.to_numeric(snap["price_m"], errors="coerce").values * 10).astype(int)
    elements["status"] = snap["status"].values
    elements["chance_of_playing_next_round"] = chance
    elements["chance_of_playing_this_round"] = chance
    elements["ep_next"] = pd.to_numeric(snap["fpl_ep_next"], errors="coerce").values
    elements["ep_this"] = elements["ep_next"]
    elements["selected_by_percent"] = pd.to_numeric(snap["ownership_pct"], errors="coerce").values
    elements["transfers_in_event"] = 0
    elements["transfers_out_event"] = 0
    elements["news"] = ""

    per90 = _per90(cap_match_history(match_df, target_gw))
    for col in PER90_COLUMNS:
        elements[col] = pid.map(lambda p, c=col: per90.get(p, {}).get(c, np.nan)).astype(float)

    return elements, _as_of_fixtures(fixtures, target_gw), teams_short_map, history_capped, dropped_ids


def actuals_for_gw(snapshots_df, history_df, gw):
    gw = int(gw)
    snaps = snapshots_df[pd.to_numeric(snapshots_df["gw"], errors="coerce") == gw]
    out = pd.DataFrame({
        "player_id": pd.to_numeric(snaps["player_id"], errors="coerce").astype(int).values,
        "actual": pd.to_numeric(snaps["actual_points"], errors="coerce").values,
        "minutes": pd.to_numeric(snaps["actual_minutes"], errors="coerce").fillna(0.0).values,
    })
    h = history_df[pd.to_numeric(history_df["gw"], errors="coerce") == gw]
    fx = dict(zip(pd.to_numeric(h["player_id"], errors="coerce").astype(int),
                  pd.to_numeric(h["gw_fixture_count"], errors="coerce").fillna(0)))
    out["had_fixture"] = out["player_id"].map(lambda p: fx.get(int(p), 0) > 0)
    return out[out["actual"].notna()].reset_index(drop=True)
