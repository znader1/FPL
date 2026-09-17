"""A/B backtest: FPL official FDR vs xG-ratings difficulty in the baseline leg.

Two difficulty systems coexist today: FPL's opinion-based FDR drives the
baseline leg's multiplier (and the D-badges), while the xG attack/defence
ratings drive the ticker, the chip planner, stack odds, and the model leg of
the blend. `PROJ_DIFFICULTY_SOURCE = "xg_ratings"` would unify them — this
script answers whether that flip helps or hurts, scored exactly like the
blend sweep (leak-safe capped history per GW, same metrics).

Both variants run at the production blend weight (0.5) so the result reflects
what would actually ship. Use --blend 0.0 to isolate the baseline leg.

    PYTHONPATH=. .venv/bin/python -m scripts.backtest_difficulty_ab
    PYTHONPATH=. .venv/bin/python -m scripts.backtest_difficulty_ab --blend 0.0 --max-gws 10
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
SOURCES = ["fpl", "xg_ratings"]


def _team_name_to_id(season="2025-26"):
    # Vaastav rows carry team NAMES; map both name and short_name to ids
    # (same shape as backtest_blend_sweep).
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


def _project(target_gw, source, blend_weight, name_to_id, horizon=1):
    elements, fixtures, teams_short, history_df = build_engine_inputs(target_gw, horizon=horizon)
    match_df = _capped_match_history(target_gw, name_to_id)

    orig_recent = projections.load_latest_player_gw_history
    orig_minutes = minutes_model.load_minutes_history
    orig_match = fixture_difficulty.load_match_history
    orig_weight = getattr(config, "PROJ_MODEL_BLEND_WEIGHT", 0.0)
    orig_source = getattr(config, "PROJ_DIFFICULTY_SOURCE", "fpl")

    projections.load_latest_player_gw_history = lambda *a, **k: history_df
    minutes_model.load_minutes_history = lambda *a, **k: history_df
    fixture_difficulty.load_match_history = lambda *a, **k: match_df
    config.PROJ_MODEL_BLEND_WEIGHT = float(blend_weight)
    config.PROJ_DIFFICULTY_SOURCE = str(source)
    try:
        proj = projections.project_elements_next_gws(
            elements=elements, fixtures=fixtures, teams_short_map=teams_short,
            gw_start=target_gw, horizon_gws=horizon,
        )
    finally:
        projections.load_latest_player_gw_history = orig_recent
        minutes_model.load_minutes_history = orig_minutes
        fixture_difficulty.load_match_history = orig_match
        config.PROJ_MODEL_BLEND_WEIGHT = orig_weight
        config.PROJ_DIFFICULTY_SOURCE = orig_source

    col = f"xpts_gw{target_gw}"
    pos = proj["pos"] if "pos" in proj.columns else proj["element_type"].map(POS_NAME)
    return pd.DataFrame({
        "player_id": pd.to_numeric(proj["id"], errors="coerce").astype("Int64"),
        "position": pos.values,
        "xpts": pd.to_numeric(proj.get(col), errors="coerce").fillna(0.0).values,
    })


def _frame_for_gw(target_gw, source, blend_weight, name_to_id):
    proj = _project(target_gw, source, blend_weight, name_to_id)
    actuals = backtest_data.player_actuals_at(target_gw)
    act = pd.DataFrame({
        "player_id": pd.to_numeric(actuals["element"], errors="coerce").astype("Int64"),
        "actual": pd.to_numeric(actuals["total_points"], errors="coerce").fillna(0.0),
        "minutes": pd.to_numeric(actuals["minutes"], errors="coerce").fillna(0.0),
    })
    return proj.merge(act, on="player_id", how="inner")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", type=float, default=None,
                    help="blend weight to hold fixed (default: production value)")
    ap.add_argument("--min-gw", type=int, default=6,
                    help="first GW to score (needs history for xG ratings)")
    ap.add_argument("--max-gws", type=int, default=None)
    args = ap.parse_args()

    blend = float(args.blend if args.blend is not None
                  else getattr(config, "PROJ_MODEL_BLEND_WEIGHT", 0.5))
    gws = [g for g in backtest_data.available_gws() if g >= args.min_gw]
    if args.max_gws:
        gws = gws[: args.max_gws]
    if not gws:
        print("No GWs available.")
        return

    name_to_id = _team_name_to_id()
    print(f"difficulty A/B — GW{min(gws)}..GW{max(gws)} ({len(gws)} GWs), blend={blend}")

    results = {}
    for source in SOURCES:
        frames = []
        for gw in gws:
            try:
                frames.append(_frame_for_gw(gw, source, blend, name_to_id))
            except Exception as exc:
                print(f"  ! {source} GW{gw} skipped: {exc}")
        if not frames:
            continue
        results[source] = {
            "mae": bm.projection_mae(frames),
            "captain_hit": bm.captain_hit_rate(frames),
            "captain_regret": bm.captain_regret(frames),
            "top10": bm.top_n_precision(frames),
        }
        print(f"  scored {source} over {len(frames)} GWs")

    if len(results) < 2:
        print("Missing a variant — no comparison.")
        return

    print(f"\n{'source':>12} {'MAE':>8} {'capt hit':>9} {'regret':>8} {'top10':>7}")
    for source in SOURCES:
        r = results[source]
        print(f"{source:>12} {r['mae']:>8.3f} {r['captain_hit']:>9.3f} "
              f"{r['captain_regret']:>8.3f} {r['top10']:>7.3f}")

    a, b = results["fpl"], results["xg_ratings"]
    d_mae = b["mae"] - a["mae"]
    verdict = "xg_ratings BETTER" if d_mae < 0 else "fpl (status quo) better or equal"
    print(f"\nd MAE (xg - fpl): {d_mae:+.4f} ({d_mae / a['mae'] * 100:+.2f}%) — {verdict}")
    print("Small margins on ~30 GWs are noise — confirm before flipping the config.")


if __name__ == "__main__":
    main()
