"""Sweep PROJ_GK_FIXTURE_DAMP: how much of the fixture-context multiplier
should apply to goalkeepers?

A keeper's floor (appearance + saves) barely moves with the opponent; only
the clean-sheet share is fixture-elastic. damp=1.0 is legacy (full stack on
the whole GK baseline). Scored leak-safe per GW like the other sweeps, with
a GK-only MAE alongside the overall metrics — the flip criterion is GK MAE
improving without overall MAE regressing.

    PYTHONPATH=. .venv/bin/python -m scripts.backtest_gk_damp
"""
import argparse

import pandas as pd

from src import (
    config,
    projections,
    minutes_model,
    fixture_difficulty,
    backtest_data,
    backtest_metrics as bm,
)
from src.backtest_adapter import build_engine_inputs

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
DEFAULT_DAMPS = [1.0, 0.7, 0.5, 0.3]


def _team_name_to_id(season="2025-26"):
    teams = backtest_data.load_teams(season)
    mapping = {}
    for _, row in teams.iterrows():
        tid = pd.to_numeric(row.get("id"), errors="coerce")
        if pd.isna(tid):
            continue
        for key in ("name", "short_name"):
            val = row.get(key)
            if isinstance(val, str) and val:
                mapping[val] = int(tid)
    return mapping


def _capped_match_history(target_gw, name_to_id, season="2025-26"):
    raw = backtest_data.player_actuals_through(target_gw - 1, season)
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    if "team_id" not in df.columns:
        df["team_id"] = df["team"].map(name_to_id) if "team" in df.columns else pd.NA
    return df[pd.to_numeric(df["team_id"], errors="coerce").notna()].copy()


def _project(target_gw, damp, name_to_id, horizon=1):
    elements, fixtures, teams_short, history_df = build_engine_inputs(target_gw, horizon=horizon)
    match_df = _capped_match_history(target_gw, name_to_id)

    orig_recent = projections.load_latest_player_gw_history
    orig_minutes = minutes_model.load_minutes_history
    orig_match = fixture_difficulty.load_match_history
    orig_damp = config.PROJ_GK_FIXTURE_DAMP

    projections.load_latest_player_gw_history = lambda *a, **k: history_df
    minutes_model.load_minutes_history = lambda *a, **k: history_df
    fixture_difficulty.load_match_history = lambda *a, **k: match_df
    config.PROJ_GK_FIXTURE_DAMP = float(damp)
    try:
        proj = projections.project_elements_next_gws(
            elements=elements, fixtures=fixtures, teams_short_map=teams_short,
            gw_start=target_gw, horizon_gws=horizon,
        )
    finally:
        projections.load_latest_player_gw_history = orig_recent
        minutes_model.load_minutes_history = orig_minutes
        fixture_difficulty.load_match_history = orig_match
        config.PROJ_GK_FIXTURE_DAMP = orig_damp

    col = f"xpts_gw{target_gw}"
    pos = proj["pos"] if "pos" in proj.columns else proj["element_type"].map(POS_NAME)
    return pd.DataFrame({
        "player_id": pd.to_numeric(proj["id"], errors="coerce").astype("Int64"),
        "position": pos.values,
        "xpts": pd.to_numeric(proj.get(col), errors="coerce").fillna(0.0).values,
    })


def _frame_for_gw(target_gw, damp, name_to_id):
    proj = _project(target_gw, damp, name_to_id)
    actuals = backtest_data.player_actuals_at(target_gw)
    act = pd.DataFrame({
        "player_id": pd.to_numeric(actuals["element"], errors="coerce").astype("Int64"),
        "actual": pd.to_numeric(actuals["total_points"], errors="coerce").fillna(0.0),
        "minutes": pd.to_numeric(actuals["minutes"], errors="coerce").fillna(0.0),
    })
    return proj.merge(act, on="player_id", how="inner")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--damps", default=None, help="comma-separated, e.g. 1.0,0.5")
    ap.add_argument("--min-gw", type=int, default=6)
    ap.add_argument("--max-gws", type=int, default=None)
    args = ap.parse_args()

    damps = ([float(d) for d in args.damps.split(",")] if args.damps else DEFAULT_DAMPS)
    gws = [g for g in backtest_data.available_gws() if g >= args.min_gw]
    if args.max_gws:
        gws = gws[: args.max_gws]
    if not gws:
        print("No GWs available.")
        return

    name_to_id = _team_name_to_id()
    print(f"GK damp sweep — GW{min(gws)}..GW{max(gws)} ({len(gws)} GWs)")

    results = {}
    for damp in damps:
        frames = []
        for gw in gws:
            try:
                frames.append(_frame_for_gw(gw, damp, name_to_id))
            except Exception as exc:
                print(f"  ! damp={damp} GW{gw} skipped: {exc}")
        if not frames:
            continue
        gk_frames = [f[f["position"] == "GKP"] for f in frames]
        results[damp] = {
            "mae": bm.projection_mae(frames),
            "gk_mae": bm.projection_mae(gk_frames, top_n=20),
            "captain_hit": bm.captain_hit_rate(frames),
            "top10": bm.top_n_precision(frames),
        }
        print(f"  scored damp {damp:.2f} over {len(frames)} GWs")

    if not results:
        print("No results.")
        return

    base = results.get(1.0)
    print(f"\n{'damp':>6} {'GK MAE':>8} {'d GK':>8} {'MAE':>8} {'d MAE':>8} {'capt':>6} {'top10':>7}")
    for damp in sorted(results, reverse=True):
        r = results[damp]
        dgk = (r["gk_mae"] - base["gk_mae"]) if base else float("nan")
        dm = (r["mae"] - base["mae"]) if base else float("nan")
        print(f"{damp:>6.2f} {r['gk_mae']:>8.3f} {dgk:>+8.3f} {r['mae']:>8.3f} "
              f"{dm:>+8.3f} {r['captain_hit']:>6.3f} {r['top10']:>7.3f}")
    print("\nFlip criterion: GK MAE down, overall MAE not up. Noise caveat applies.")


if __name__ == "__main__":
    main()
