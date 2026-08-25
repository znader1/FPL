"""
Minutes A/B backtest (guide, not a gate).

Walk-forward GW3 -> max available on 2025-26 Vaastav data: project each GW with
PROJ_APPLY_MINUTES_MODEL off vs on, score projected xpts against actual points,
and print MAE / captain hit-rate / captain regret / top-10 precision side by side.

Patches BOTH history loaders to the capped history so the minutes model never
peeks at the future. Restores loaders + the flag every iteration.

    .venv/bin/python -m scripts.backtest_minutes_ab
"""
import pandas as pd

from src import (
    config,
    projections,
    minutes_model,
    backtest_data,
    backtest_metrics as bm,
)
from src.backtest_adapter import build_engine_inputs

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _project(target_gw, apply_minutes, horizon=3):
    elements, fixtures, teams_short, history_df = build_engine_inputs(target_gw, horizon=horizon)
    orig_recent = projections.load_latest_player_gw_history
    orig_minutes = minutes_model.load_minutes_history
    orig_flag = getattr(config, "PROJ_APPLY_MINUTES_MODEL", False)
    projections.load_latest_player_gw_history = lambda *a, **k: history_df
    minutes_model.load_minutes_history = lambda *a, **k: history_df
    config.PROJ_APPLY_MINUTES_MODEL = apply_minutes
    try:
        proj = projections.project_elements_next_gws(
            elements=elements, fixtures=fixtures, teams_short_map=teams_short,
            gw_start=target_gw, horizon_gws=horizon,
        )
    finally:
        projections.load_latest_player_gw_history = orig_recent
        minutes_model.load_minutes_history = orig_minutes
        config.PROJ_APPLY_MINUTES_MODEL = orig_flag

    col = f"xpts_gw{target_gw}"
    pos = proj["pos"] if "pos" in proj.columns else proj["element_type"].map(POS_NAME)
    return pd.DataFrame({
        "player_id": pd.to_numeric(proj["id"], errors="coerce").astype("Int64"),
        "position": pos.values,
        "xpts": pd.to_numeric(proj.get(col), errors="coerce").fillna(0.0).values,
    })


def _frame_for_gw(target_gw, apply_minutes):
    proj = _project(target_gw, apply_minutes)
    actuals = backtest_data.player_actuals_at(target_gw)
    act = pd.DataFrame({
        "player_id": pd.to_numeric(actuals["element"], errors="coerce").astype("Int64"),
        "actual": pd.to_numeric(actuals["total_points"], errors="coerce").fillna(0.0),
        "minutes": pd.to_numeric(actuals["minutes"], errors="coerce").fillna(0.0),
    })
    return proj.merge(act, on="player_id", how="inner")


def main():
    gws = [g for g in backtest_data.available_gws() if g >= 3]
    if not gws:
        print("No Vaastav GWs >= 3 available.")
        return
    print(f"Minutes A/B backtest — GW{min(gws)}..GW{max(gws)} ({len(gws)} GWs)\n")

    frames_off, frames_on = [], []
    for gw in gws:
        try:
            frames_off.append(_frame_for_gw(gw, False))
            frames_on.append(_frame_for_gw(gw, True))
        except Exception as exc:
            print(f"  ! GW{gw} skipped: {exc}")

    def _row(label, off_val, on_val, better="lower"):
        delta = on_val - off_val
        arrow = "better" if (delta < 0) == (better == "lower") and abs(delta) > 1e-9 else (
            "worse" if abs(delta) > 1e-9 else "flat")
        return f"{label:24} {off_val:8.3f} {on_val:8.3f} {delta:+8.3f}  {arrow}"

    print(f"{'metric':24} {'OFF':>8} {'ON':>8} {'delta':>8}")
    print(_row("projection MAE", bm.projection_mae(frames_off), bm.projection_mae(frames_on), "lower"))
    print(_row("captain hit-rate", bm.captain_hit_rate(frames_off), bm.captain_hit_rate(frames_on), "higher"))
    print(_row("captain regret", bm.captain_regret(frames_off), bm.captain_regret(frames_on), "lower"))
    print(_row("top-10 precision", bm.top_n_precision(frames_off), bm.top_n_precision(frames_on), "higher"))

    print("\nMAE by position (OFF -> ON):")
    off_pos, on_pos = bm.mae_by_position(frames_off), bm.mae_by_position(frames_on)
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        if pos in off_pos or pos in on_pos:
            print(f"  {pos:4} {off_pos.get(pos, float('nan')):7.3f} -> {on_pos.get(pos, float('nan')):7.3f}")

    print("\nGuide only — n_gws is small; read directionally. Ownership-EV (SP2) is NOT "
          "backtestable (no historical ownership).")


if __name__ == "__main__":
    main()
