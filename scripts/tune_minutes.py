"""
Grid-search the minutes-model coefficients against the walk-forward A/B harness.

For each (MINUTES_NAILED_START_REF, MINUTES_CAMEO_POINT_VALUE) combo, project
GW3..max with PROJ_APPLY_MINUTES_MODEL on and compare projection MAE / captain
hit-rate against the OFF baseline. Read-only: sets config attributes in-process
only; never writes config.py.

Per-GW engine inputs + actuals are cached (deterministic) so the sweep only pays
the projection cost, not repeated CSV reads.

    .venv/bin/python -m scripts.tune_minutes
"""
import pandas as pd

from src import config, projections, minutes_model, backtest_data
from src import backtest_metrics as bm
from src.backtest_adapter import build_engine_inputs

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
NAILED_REF_GRID = [0.50, 0.60, 0.70, 0.80, 0.85, 0.90]
CAMEO_GRID = [0.0, 0.15, 0.30]

_INPUTS = {}
_ACTUALS = {}


def _inputs(gw, horizon=3):
    if gw not in _INPUTS:
        _INPUTS[gw] = build_engine_inputs(gw, horizon=horizon)
    return _INPUTS[gw]


def _actuals(gw):
    if gw not in _ACTUALS:
        a = backtest_data.player_actuals_at(gw)
        _ACTUALS[gw] = pd.DataFrame({
            "player_id": pd.to_numeric(a["element"], errors="coerce").astype("Int64"),
            "actual": pd.to_numeric(a["total_points"], errors="coerce").fillna(0.0),
            "minutes": pd.to_numeric(a["minutes"], errors="coerce").fillna(0.0),
        })
    return _ACTUALS[gw]


def _project(gw, apply_minutes, horizon=3):
    elements, fixtures, teams_short, history_df = _inputs(gw, horizon)
    orig_recent = projections.load_latest_player_gw_history
    orig_minutes = minutes_model.load_minutes_history
    orig_flag = getattr(config, "PROJ_APPLY_MINUTES_MODEL", False)
    projections.load_latest_player_gw_history = lambda *a, **k: history_df
    minutes_model.load_minutes_history = lambda *a, **k: history_df
    config.PROJ_APPLY_MINUTES_MODEL = apply_minutes
    try:
        proj = projections.project_elements_next_gws(
            elements=elements, fixtures=fixtures, teams_short_map=teams_short,
            gw_start=gw, horizon_gws=horizon,
        )
    finally:
        projections.load_latest_player_gw_history = orig_recent
        minutes_model.load_minutes_history = orig_minutes
        config.PROJ_APPLY_MINUTES_MODEL = orig_flag

    col = f"xpts_gw{gw}"
    pos = proj["pos"] if "pos" in proj.columns else proj["element_type"].map(POS_NAME)
    projd = pd.DataFrame({
        "player_id": pd.to_numeric(proj["id"], errors="coerce").astype("Int64"),
        "position": pos.values,
        "xpts": pd.to_numeric(proj.get(col), errors="coerce").fillna(0.0).values,
    })
    return projd.merge(_actuals(gw), on="player_id", how="inner")


def _metrics(apply_minutes, gws):
    frames = [_project(g, apply_minutes) for g in gws]
    return {
        "mae": bm.projection_mae(frames),
        "hit": bm.captain_hit_rate(frames),
        "regret": bm.captain_regret(frames),
        "prec": bm.top_n_precision(frames),
    }


def main():
    gws = [g for g in backtest_data.available_gws() if g >= 3]
    if not gws:
        print("No Vaastav GWs >= 3 available.")
        return
    print(f"Tuning minutes model — GW{min(gws)}..GW{max(gws)} ({len(gws)} GWs)\n")

    base = _metrics(False, gws)
    print(f"BASELINE (OFF):  MAE={base['mae']:.3f}  hit={base['hit']:.3f}  "
          f"regret={base['regret']:.3f}  prec={base['prec']:.3f}\n")

    print(f"{'nailed_ref':>10} {'cameo':>6} {'MAE':>7} {'dMAE':>7} {'hit':>6} {'dhit':>7} {'prec':>6}")
    results = []
    for nr in NAILED_REF_GRID:
        for cv in CAMEO_GRID:
            config.MINUTES_NAILED_START_REF = nr
            config.MINUTES_CAMEO_POINT_VALUE = cv
            r = _metrics(True, gws)
            results.append((nr, cv, r))
            dmae = r["mae"] - base["mae"]
            dhit = r["hit"] - base["hit"]
            flag = "  <= beats OFF MAE" if dmae < -1e-9 else ""
            print(f"{nr:>10.2f} {cv:>6.2f} {r['mae']:>7.3f} {dmae:>+7.3f} "
                  f"{r['hit']:>6.3f} {dhit:>+7.3f} {r['prec']:>6.3f}{flag}")

    best = min(results, key=lambda g: g[2]["mae"])
    bmae = best[2]["mae"]
    print(f"\nBest MAE combo: nailed_ref={best[0]} cameo={best[1]} -> MAE {bmae:.3f} "
          f"(baseline {base['mae']:.3f}, delta {bmae - base['mae']:+.3f})")
    if bmae < base["mae"] - 1e-9:
        print("=> A calibration beats the OFF baseline on MAE. Candidate to enable with these coefficients.")
    else:
        print("=> No calibration beats the OFF baseline on MAE. Keep PROJ_APPLY_MINUTES_MODEL off this cycle.")
    print("\nNote: backtest elements are uniformly available (status=a/chance=100), so OFF = no discount; "
          "this isolates the rotation multiplier. Immediate-GW metric only (future-GW fade not exercised).")


if __name__ == "__main__":
    main()
