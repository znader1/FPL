#!/usr/bin/env python3
import argparse
from pathlib import Path

import pandas as pd


DIFFICULTY_MULTIPLIER = {
    1: 1.15,
    2: 1.08,
    3: 1.00,
    4: 0.93,
    5: 0.86,
}


def difficulty_multiplier(diff_avg):
    if pd.isna(diff_avg):
        return 1.0
    try:
        d = int(round(float(diff_avg)))
    except Exception:
        return 1.0
    d = max(1, min(5, d))
    return float(DIFFICULTY_MULTIPLIER.get(d, 1.0))


def find_latest_gw_history(base_dir="data/processed/fpl"):
    base = Path(base_dir)
    if not base.exists():
        return None
    paths = list(base.glob("*/player_gw_history_*.csv"))
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def spearman_rank_corr(a, b):
    ar = pd.Series(a).rank(method="average")
    br = pd.Series(b).rank(method="average")
    return ar.corr(br)


def main():
    ap = argparse.ArgumentParser(description="Backtest a simple baseline on player_gw_history_*.csv")
    ap.add_argument("--input", default="", help="Path to player_gw_history_<season>.csv")
    ap.add_argument("--window", type=int, default=3, help="Rolling window (GWs) for baseline form")
    ap.add_argument("--min-gw", type=int, default=2, help="Evaluate from this GW (inclusive)")
    ap.add_argument("--topk", type=int, default=25, help="Top-K overlap metric")
    args = ap.parse_args()

    path = Path(args.input) if args.input else find_latest_gw_history()
    if not path or not Path(path).exists():
        print("No input found. Provide --input or generate data with: python -m src.season_history --resume")
        return 2

    df = pd.read_csv(path)
    if df.empty:
        print(f"Empty file: {path}")
        return 2

    required = ["player_id", "gw", "gw_total_points", "gw_fixture_count"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"Missing required columns: {missing}")
        print(f"Columns present: {list(df.columns)}")
        return 2

    df["gw"] = pd.to_numeric(df["gw"], errors="coerce")
    df = df[df["gw"].notna()].copy()
    df["gw"] = df["gw"].astype(int)
    df = df.sort_values(["player_id", "gw"])

    # Baseline: rolling mean of past `window` GW points (shifted)
    window = int(args.window)
    df["pred_base"] = (
        df.groupby("player_id")["gw_total_points"]
        .apply(lambda s: s.shift(1).rolling(window, min_periods=1).mean())
        .reset_index(level=0, drop=True)
    )

    diff_col = "gw_team_difficulty_avg" if "gw_team_difficulty_avg" in df.columns else None
    if diff_col:
        df["diff_mult"] = pd.to_numeric(df[diff_col], errors="coerce").apply(difficulty_multiplier)
    else:
        df["diff_mult"] = 1.0

    df["gw_fixture_count"] = pd.to_numeric(df["gw_fixture_count"], errors="coerce").fillna(0.0)

    # Predict: baseline × (number of fixtures) × (difficulty multiplier)
    df["pred"] = df["pred_base"].fillna(0.0) * df["gw_fixture_count"] * df["diff_mult"]

    # Eval frame
    df_eval = df[df["gw"] >= int(args.min_gw)].copy()
    df_eval["actual"] = pd.to_numeric(df_eval["gw_total_points"], errors="coerce").fillna(0.0)

    mae = (df_eval["pred"] - df_eval["actual"]).abs().mean()

    # Per-GW rank correlation + topK overlap
    rows = []
    for gw, g in df_eval.groupby("gw"):
        if len(g) < 10:
            continue
        corr = spearman_rank_corr(g["pred"], g["actual"])

        topk = int(args.topk)
        pred_top = set(g.sort_values("pred", ascending=False).head(topk)["player_id"].astype(int).tolist())
        act_top = set(g.sort_values("actual", ascending=False).head(topk)["player_id"].astype(int).tolist())
        overlap = len(pred_top.intersection(act_top))

        rows.append({"gw": int(gw), "spearman": float(corr) if corr == corr else None, "topk_overlap": overlap})

    per_gw = pd.DataFrame(rows).sort_values("gw") if rows else pd.DataFrame()
    avg_spearman = per_gw["spearman"].mean() if not per_gw.empty else None
    avg_overlap = per_gw["topk_overlap"].mean() if not per_gw.empty else None

    print(f"Input: {path}")
    print(f"Rows evaluated: {len(df_eval):,} | Players: {df_eval['player_id'].nunique():,} | GWs: {df_eval['gw'].nunique():,}")
    print(f"MAE (overall): {mae:.3f}")
    if avg_spearman is not None:
        print(f"Avg Spearman (per GW): {avg_spearman:.3f}")
    if avg_overlap is not None:
        print(f"Avg top{int(args.topk)} overlap (per GW): {avg_overlap:.2f}")

    if not per_gw.empty:
        print("\nPer GW:")
        print(per_gw.to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

