"""Prediction-vs-actual monitoring and the rollback rule (calibration spec, part 6).

Pure functions over ``player_gw_snapshots`` rows. ``model_xpts`` is the live
record; ``runner_xpts`` / ``shadow_xpts`` are the current and previous model
computed on the same runner data, so comparing them isolates the model change.

Rollback rule: after ROLLBACK_MIN_GWS finished GWs, roll back when the shadow's
overall 1-GW MAE is more than ROLLBACK_MAE_MARGIN below the live model's, or
when the live model's price-band bias is worse than the shadow's.
"""
from __future__ import annotations

import pandas as pd

from src.backtest_metrics import band_bias, calibration_table

ROLLBACK_MIN_GWS = 3
ROLLBACK_MAE_MARGIN = 0.01
NO_FIXTURE_XPTS = 0.5


def frames_from_snapshots(rows_df, column, history_df=None):
    d = rows_df.copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    d = d[d["actual_points"].notna() & pd.to_numeric(d[column], errors="coerce").notna()]
    fixture = None
    if history_df is not None and not history_df.empty:
        h = history_df
        fixture = {(int(g), int(p)): c > 0 for g, p, c in zip(
            h["gw"], h["player_id"], pd.to_numeric(h["gw_fixture_count"], errors="coerce").fillna(0))}
    frames = []
    for gw, g in d.groupby("gw"):
        mins = pd.to_numeric(g["actual_minutes"], errors="coerce").fillna(0.0)
        if fixture is not None:
            had = [fixture.get((int(gw), int(p)), False) for p in g["player_id"]]
        else:
            had = (mins > 0) | (pd.to_numeric(g["model_xpts"], errors="coerce").fillna(0.0) > NO_FIXTURE_XPTS)
        frames.append(pd.DataFrame({
            "player_id": pd.to_numeric(g["player_id"], errors="coerce").astype(int).values,
            "position": g["pos"].values,
            "price_m": pd.to_numeric(g["price_m"], errors="coerce").values,
            "xpts": pd.to_numeric(g[column], errors="coerce").values,
            "actual": g["actual_points"].values,
            "minutes": mins.values,
            "had_fixture": list(had),
            "gw": int(gw),
        }))
    return frames


def summarize(frames):
    table = calibration_table(frames)
    all_row = table[table["pos"] == "ALL"]
    mae = float(all_row["mae"].iloc[0]) if len(all_row) else float("nan")
    return {"table": table, "mae": mae, "band_bias": band_bias(table)}


def rollback_verdict(live_frames, shadow_frames, gws_since_ship):
    if int(gws_since_ship) < ROLLBACK_MIN_GWS:
        return "wait"
    live, shadow = summarize(live_frames), summarize(shadow_frames)
    if shadow["mae"] < live["mae"] * (1 - ROLLBACK_MAE_MARGIN):
        return "rollback"
    if live["band_bias"] > shadow["band_bias"]:
        return "rollback"
    return "keep"
