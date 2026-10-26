"""
Live-season replay: score candidate projection settings on this season's
finished gameweeks, through the production projection code.

For each target GW the engine gets as-of inputs (src/season_replay.py): the
pre-deadline snapshot row for that GW plus history strictly before it. The three
history loaders the engine reads are patched per GW, exactly as
scripts/backtest_blend_sweep.py does, so nothing from the target GW or later
leaks in. Candidates are config overrides (src/config_overrides.py).

Ranking follows the 2026-10-26 calibration spec: a candidate is eligible only if
its tune-GW 1-GW MAE is within 1% of the current config's; eligible candidates
are ranked by price-band bias (mean |bias| over position x price-band cells).
The hold-out GWs are reported, never used to rank.

    PYTHONPATH=. .venv/bin/python -m scripts.backtest_live_season \
        --snapshots-csv data/replay/snapshots_2026-27.csv --tune-gws 3-6 --holdout-gws 7-8 \
        --grid "PROJ_SHRINKAGE_GAMES=5,2.5,0;PROJ_MODEL_BLEND_WEIGHT=0.5,0.6,0.7;PROJ_FDR_STRENGTH=1,1.5,2"
"""
from __future__ import annotations

import argparse
import itertools
import logging
import warnings

import pandas as pd

from src import backtest_metrics as bm
from src import config, fixture_difficulty, minutes_model, projections, season_replay
from src.config_overrides import config_overrides

MAE_TOLERANCE = 0.01
TOP_K = 3


def parse_grid(spec):
    """'A=1,2;B=3' -> [{'A': 1.0, 'B': 3.0}, {'A': 2.0, 'B': 3.0}]; '' -> [{}]."""
    axes = []
    for part in (spec or "").split(";"):
        part = part.strip()
        if not part:
            continue
        key, _, values = part.partition("=")
        axes.append([(key.strip(), float(v)) for v in values.split(",") if v.strip()])
    if not axes:
        return [{}]
    return [dict(combo) for combo in itertools.product(*axes)]


def parse_gws(spec):
    lo, _, hi = str(spec).partition("-")
    return list(range(int(lo), int(hi or lo) + 1))


def score_window_starts(gws, horizon):
    have = set(gws)
    return [g for g in sorted(gws) if all(g + i in have for i in range(int(horizon)))]


def project_gw(target_gw, horizon, overrides, inputs):
    elements, fixtures, short, history_capped, _ = season_replay.build_live_engine_inputs(
        target_gw, horizon, inputs["bootstrap"], inputs["fixtures"], inputs["history_df"],
        inputs["snapshots_df"], match_df=inputs["match_df"],
    )
    match_capped = season_replay.cap_match_history(inputs["match_df"], target_gw)
    orig = (projections.load_latest_player_gw_history, minutes_model.load_minutes_history,
            fixture_difficulty.load_match_history)
    projections.load_latest_player_gw_history = lambda *a, **k: history_capped
    minutes_model.load_minutes_history = lambda *a, **k: history_capped
    fixture_difficulty.load_match_history = lambda *a, **k: match_capped
    try:
        with config_overrides(overrides):
            return projections.project_elements_next_gws(
                elements=elements, fixtures=fixtures, teams_short_map=short,
                gw_start=int(target_gw), horizon_gws=int(horizon),
                finished_gw_max=int(target_gw) - 1,
            )
    finally:
        (projections.load_latest_player_gw_history, minutes_model.load_minutes_history,
         fixture_difficulty.load_match_history) = orig


def replay_frames(gws, horizon, overrides, inputs):
    """One calibration frame per full window start (see backtest_metrics)."""
    frames = []
    for start in score_window_starts(gws, horizon):
        window = [start + i for i in range(int(horizon))]
        proj = project_gw(start, horizon, overrides, inputs)
        xpts = sum(pd.to_numeric(proj.get(f"xpts_gw{g}"), errors="coerce").fillna(0.0) for g in window)
        pred = pd.DataFrame({
            "player_id": pd.to_numeric(proj["id"], errors="coerce").astype(int).values,
            "position": proj["pos"].values,
            "price_m": pd.to_numeric(proj["now_cost"], errors="coerce").values / 10.0,
            "xpts": pd.Series(xpts).values,
        })
        acts = [season_replay.actuals_for_gw(inputs["snapshots_df"], inputs["history_df"], g)
                for g in window]
        act = pd.concat(acts, ignore_index=True).groupby("player_id").agg(
            actual=("actual", "sum"), minutes=("minutes", "sum"), had_fixture=("had_fixture", "any"),
        ).reset_index()
        frame = pred.merge(act, on="player_id", how="inner")
        frame["gw"] = start
        frames.append(frame)
    return frames


def parity_stats(proj, snapshots_df, gw):
    """Replay xPts vs the stored pre-deadline model_xpts for one GW."""
    snaps = snapshots_df[pd.to_numeric(snapshots_df["gw"], errors="coerce") == int(gw)]
    stored = pd.DataFrame({
        "id": pd.to_numeric(snaps["player_id"], errors="coerce").astype(int).values,
        "stored": pd.to_numeric(snaps["model_xpts"], errors="coerce").values,
    })
    replay = pd.DataFrame({
        "id": pd.to_numeric(proj["id"], errors="coerce").astype(int).values,
        "replay": pd.to_numeric(proj[f"xpts_gw{int(gw)}"], errors="coerce").values,
    })
    both = replay.merge(stored, on="id").dropna()
    if both.empty:
        return {"n": 0, "mae": float("nan"), "corr": float("nan")}
    return {"n": int(len(both)), "mae": float((both["replay"] - both["stored"]).abs().mean()),
            "corr": float(both["replay"].corr(both["stored"]))}


def _summary(frames):
    table = bm.calibration_table(frames)
    overall = table[table["pos"] == "ALL"].iloc[0] if not table.empty else None
    return table, (float(overall["mae"]) if overall is not None else float("nan")), bm.band_bias(table)


def _label(overrides):
    return ", ".join(f"{k}={v:g}" for k, v in overrides.items()) or "current config"


def _load_inputs(snapshots_csv):
    from api import main as api_main
    history_path = projections.find_latest_gw_history()
    match_path = fixture_difficulty.find_latest_match_history()
    if not history_path or not match_path:
        raise SystemExit("No local history: run the data refresh first (see the module docstring).")
    return {
        "bootstrap": api_main.get_bootstrap_cached(),
        "fixtures": api_main.get_fixtures_cached(),
        "history_df": pd.read_csv(history_path),
        "match_df": pd.read_csv(match_path),
        "snapshots_df": pd.read_csv(snapshots_csv),
    }


def main():
    warnings.simplefilter("ignore")
    logging.basicConfig(level=logging.ERROR)
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots-csv", required=True)
    ap.add_argument("--tune-gws", default="3-6")
    ap.add_argument("--holdout-gws", default="7-8")
    ap.add_argument("--horizon", type=int, default=1)
    ap.add_argument("--grid", default="")
    ap.add_argument("--out", default=None, help="CSV of every candidate's summary")
    ap.add_argument("--parity-gw", type=int, default=None,
                    help="also compare the current config's replay of this GW with the stored "
                         "model_xpts (needs a model_xpts column in the snapshots CSV)")
    args = ap.parse_args()

    inputs = _load_inputs(args.snapshots_csv)
    if args.parity_gw is not None:
        s = parity_stats(project_gw(args.parity_gw, 1, {}, inputs), inputs["snapshots_df"], args.parity_gw)
        print(f"Parity GW{args.parity_gw}: n {s['n']}  mean |replay - stored| {s['mae']:.3f}  corr {s['corr']:.3f}\n")
    tune, hold = parse_gws(args.tune_gws), parse_gws(args.holdout_gws)
    candidates = [{}] + [c for c in parse_grid(args.grid) if c]
    pd.set_option("display.width", 220)

    results = []
    for cand in candidates:
        tune_frames = replay_frames(tune, args.horizon, cand, inputs)
        _, mae, bias = _summary(tune_frames)
        results.append({"overrides": cand, "label": _label(cand), "tune_mae": mae,
                        "tune_band_bias": bias, "tune_frames": tune_frames})
        print(f"  {results[-1]['label']:<70} tune MAE {mae:.3f}  band bias {bias:.3f}")

    current = results[0]
    limit = current["tune_mae"] * (1 + MAE_TOLERANCE)
    eligible = [r for r in results[1:] if r["tune_mae"] <= limit]
    ranked = sorted(eligible, key=lambda r: r["tune_band_bias"])[:TOP_K]

    print(f"\nHorizon {args.horizon} GW · tune GW{tune[0]}-{tune[-1]} · hold-out GW{hold[0]}-{hold[-1]}")
    print(f"MAE gate: tune MAE <= {limit:.3f} (current {current['tune_mae']:.3f} + 1%)")
    print(f"{len(eligible)} of {len(results) - 1} candidates pass the gate; top {len(ranked)} by band bias below.\n")
    for r in [current] + ranked:
        hold_frames = replay_frames(hold, args.horizon, r["overrides"], inputs)
        table, h_mae, h_bias = _summary(hold_frames)
        r.update({"hold_mae": h_mae, "hold_band_bias": h_bias})
        print(f"=== {r['label']}")
        print(f"tune MAE {r['tune_mae']:.3f} band bias {r['tune_band_bias']:.3f} | "
              f"hold-out MAE {h_mae:.3f} band bias {h_bias:.3f}")
        for f in r["tune_frames"] + hold_frames:
            _, g_mae, g_bias = _summary([f])
            print(f"  GW{int(f['gw'].iloc[0])}: MAE {g_mae:.3f} band bias {g_bias:.3f}")
        print(table.round(3).to_string(index=False))
        print()

    if args.out:
        pd.DataFrame([{k: v for k, v in r.items() if k not in ("tune_frames", "overrides")}
                      for r in results]).to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
