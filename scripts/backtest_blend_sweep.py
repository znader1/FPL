"""
Blend-weight sweep for the xG expected-points model (Stage 0).

`PROJ_MODEL_BLEND_WEIGHT` is 0.0 in config, so the whole xG stack
(fixture_difficulty + minutes_model + output_model) is built but never runs in
production. This walks that weight across a range and scores each setting the
same way the minutes A/B does, so we can answer one question before spending
money on better inputs: does the model beat the baseline at any weight?

Leak safety: `expected_points.build_expected_points` loads the *full* match
history when the caller doesn't pass one, which in a backtest means future
gameweeks. All three loaders are patched per GW to a history capped at
`target_gw - 1` and restored afterwards:

    projections.load_latest_player_gw_history  (recency blend)
    minutes_model.load_minutes_history         (P(start), E[minutes])
    fixture_difficulty.load_match_history      (team attack/defence ratings)

The raw Vaastav rows carry team *names*, while fixture_difficulty keys on
`team_id`, so the capped frame gets an id column mapped from the team table.

    PYTHONPATH=. .venv/bin/python -m scripts.backtest_blend_sweep
    PYTHONPATH=. .venv/bin/python -m scripts.backtest_blend_sweep --weights 0,0.25,0.5 --max-gws 10
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
from src.backtest_adapter import build_engine_inputs, build_history_df

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
DEFAULT_WEIGHTS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]


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
    """Raw per-player-per-match rows strictly before `target_gw`, with team_id."""
    raw = backtest_data.player_actuals_through(target_gw - 1, season)
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    if "team_id" not in df.columns:
        df["team_id"] = df["team"].map(name_to_id) if "team" in df.columns else pd.NA
    return df[pd.to_numeric(df["team_id"], errors="coerce").notna()].copy()


def _project(target_gw, weight, name_to_id, horizon=1):
    elements, fixtures, teams_short, history_df = build_engine_inputs(target_gw, horizon=horizon)
    match_df = _capped_match_history(target_gw, name_to_id)

    orig_recent = projections.load_latest_player_gw_history
    orig_minutes = minutes_model.load_minutes_history
    orig_match = fixture_difficulty.load_match_history
    orig_weight = getattr(config, "PROJ_MODEL_BLEND_WEIGHT", 0.0)

    projections.load_latest_player_gw_history = lambda *a, **k: history_df
    minutes_model.load_minutes_history = lambda *a, **k: history_df
    fixture_difficulty.load_match_history = lambda *a, **k: match_df
    config.PROJ_MODEL_BLEND_WEIGHT = float(weight)
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

    col = f"xpts_gw{target_gw}"
    pos = proj["pos"] if "pos" in proj.columns else proj["element_type"].map(POS_NAME)
    return pd.DataFrame({
        "player_id": pd.to_numeric(proj["id"], errors="coerce").astype("Int64"),
        "position": pos.values,
        "xpts": pd.to_numeric(proj.get(col), errors="coerce").fillna(0.0).values,
    })


def _frame_for_gw(target_gw, weight, name_to_id):
    proj = _project(target_gw, weight, name_to_id)
    actuals = backtest_data.player_actuals_at(target_gw)
    act = pd.DataFrame({
        "player_id": pd.to_numeric(actuals["element"], errors="coerce").astype("Int64"),
        "actual": pd.to_numeric(actuals["total_points"], errors="coerce").fillna(0.0),
        "minutes": pd.to_numeric(actuals["minutes"], errors="coerce").fillna(0.0),
    })
    return proj.merge(act, on="player_id", how="inner")


def _model_is_live(target_gw, name_to_id):
    """True when the xG stack actually produces numbers for this GW.

    Without this a sweep over an unavailable model reads as 'no weight helps',
    when the real finding is 'the model never ran'.
    """
    match_df = _capped_match_history(target_gw, name_to_id)
    if match_df.empty:
        return False
    return not fixture_difficulty.build_team_match_xg(match_df).empty


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=None, help="comma-separated, e.g. 0,0.25,0.5")
    ap.add_argument("--min-gw", type=int, default=6,
                    help="first GW to score (needs enough history for xG ratings)")
    ap.add_argument("--max-gws", type=int, default=None, help="cap the number of GWs")
    args = ap.parse_args()

    weights = ([float(w) for w in args.weights.split(",")] if args.weights else DEFAULT_WEIGHTS)
    gws = [g for g in backtest_data.available_gws() if g >= args.min_gw]
    if args.max_gws:
        gws = gws[: args.max_gws]
    if not gws:
        print("No GWs available.")
        return

    name_to_id = _team_name_to_id()

    live = _model_is_live(gws[0], name_to_id)
    print(f"xG blend sweep — GW{min(gws)}..GW{max(gws)} ({len(gws)} GWs)")
    print(f"xG model produces ratings at GW{gws[0]}: {live}")
    if not live:
        print("\nThe xG stack has no usable data, so every weight will score identically.")
        print("Fix the inputs before reading anything into the table below.\n")

    results = {}
    for w in weights:
        frames = []
        for gw in gws:
            try:
                frames.append(_frame_for_gw(gw, w, name_to_id))
            except Exception as exc:
                print(f"  ! w={w} GW{gw} skipped: {exc}")
        if not frames:
            continue
        results[w] = {
            "mae": bm.projection_mae(frames),
            "captain_hit": bm.captain_hit_rate(frames),
            "captain_regret": bm.captain_regret(frames),
            "top10": bm.top_n_precision(frames),
        }
        print(f"  scored weight {w:.2f} over {len(frames)} GWs")

    if not results:
        print("No results.")
        return

    base = results.get(0.0)
    print(f"\n{'weight':>7} {'MAE':>8} {'d MAE':>8} {'capt hit':>9} {'regret':>8} {'top10':>7}")
    for w in sorted(results):
        r = results[w]
        d = (r["mae"] - base["mae"]) if base else float("nan")
        print(f"{w:7.2f} {r['mae']:8.3f} {d:+8.3f} {r['captain_hit']:9.3f} "
              f"{r['captain_regret']:8.3f} {r['top10']:7.3f}")

    if base:
        better = [w for w in results if w > 0 and results[w]["mae"] < base["mae"] - 1e-9]
        print()
        if better:
            best = min(better, key=lambda w: results[w]["mae"])
            gain = base["mae"] - results[best]["mae"]
            print(f"Best weight {best:.2f}: MAE {gain:.4f} lower than baseline "
                  f"({100 * gain / base['mae']:.2f}% better).")
            print("Small margins on ~30 GWs are noise — confirm before shipping.")
        else:
            print("No weight beat the baseline MAE. Keep PROJ_MODEL_BLEND_WEIGHT at 0.0.")


if __name__ == "__main__":
    main()
