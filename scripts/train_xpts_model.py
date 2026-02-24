#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


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


def parse_season_label(path):
    stem = Path(path).stem
    if "player_gw_history_" in stem:
        return stem.replace("player_gw_history_", "")
    return "unknown-season"


def load_history(path):
    df = pd.read_csv(path)
    required = ["player_id", "gw", "gw_total_points", "gw_fixture_count"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    numeric_cols = [
        "player_id",
        "gw",
        "gw_total_points",
        "gw_fixture_count",
        "gw_minutes",
        "gw_starts",
        "gw_team_difficulty_avg",
        "gw_opp_difficulty_avg",
        "gw_value_end",
        "gw_selected_end",
        "gw_transfers_balance_end",
        "gw_transfers_in_end",
        "gw_transfers_out_end",
        "element_type",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[df["player_id"].notna() & df["gw"].notna()].copy()
    df["player_id"] = df["player_id"].astype(int)
    df["gw"] = df["gw"].astype(int)
    df = df.sort_values(["player_id", "gw"]).reset_index(drop=True)
    return df


def add_features(df):
    work = df.copy()
    grp = work.groupby("player_id")

    work["f_lag_pts_1"] = grp["gw_total_points"].shift(1)
    work["f_lag_pts_2"] = grp["gw_total_points"].shift(2)
    work["f_lag_pts_3"] = grp["gw_total_points"].shift(3)

    work["f_roll_pts_3"] = grp["gw_total_points"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    work["f_roll_pts_5"] = grp["gw_total_points"].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    work["f_last_minutes"] = grp["gw_minutes"].shift(1) if "gw_minutes" in work.columns else np.nan
    work["f_roll_minutes_3"] = (
        grp["gw_minutes"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
        if "gw_minutes" in work.columns
        else np.nan
    )
    work["f_last_starts"] = grp["gw_starts"].shift(1) if "gw_starts" in work.columns else np.nan

    work["f_fixture_count"] = work["gw_fixture_count"]
    work["f_team_diff"] = work["gw_team_difficulty_avg"] if "gw_team_difficulty_avg" in work.columns else np.nan
    work["f_opp_diff"] = work["gw_opp_difficulty_avg"] if "gw_opp_difficulty_avg" in work.columns else np.nan
    work["f_value"] = work["gw_value_end"] if "gw_value_end" in work.columns else np.nan
    work["f_selected"] = work["gw_selected_end"] if "gw_selected_end" in work.columns else np.nan
    work["f_transfers_balance"] = work["gw_transfers_balance_end"] if "gw_transfers_balance_end" in work.columns else np.nan
    work["f_transfers_in"] = work["gw_transfers_in_end"] if "gw_transfers_in_end" in work.columns else np.nan
    work["f_transfers_out"] = work["gw_transfers_out_end"] if "gw_transfers_out_end" in work.columns else np.nan
    work["f_gw_index"] = work["gw"]

    element_type = work["element_type"] if "element_type" in work.columns else pd.Series(np.nan, index=work.index)
    for pos_id in [1, 2, 3, 4]:
        work[f"f_pos_{pos_id}"] = (element_type == pos_id).astype(float)

    work["target_points"] = work["gw_total_points"].fillna(0.0)
    return work


def get_feature_columns(df):
    cols = [
        "f_lag_pts_1",
        "f_lag_pts_2",
        "f_lag_pts_3",
        "f_roll_pts_3",
        "f_roll_pts_5",
        "f_last_minutes",
        "f_roll_minutes_3",
        "f_last_starts",
        "f_fixture_count",
        "f_team_diff",
        "f_opp_diff",
        "f_value",
        "f_selected",
        "f_transfers_balance",
        "f_transfers_in",
        "f_transfers_out",
        "f_gw_index",
        "f_pos_1",
        "f_pos_2",
        "f_pos_3",
        "f_pos_4",
    ]
    return [c for c in cols if c in df.columns]


def split_train_valid(df, train_max_gw=26, valid_gws=3):
    available_max = int(df["gw"].max())
    used_max = min(int(train_max_gw), available_max)

    work = df[df["gw"] <= used_max].copy()
    if work.empty:
        raise ValueError("No rows available after GW filter.")

    valid_gws = max(1, int(valid_gws))
    valid_start = max(int(work["gw"].min()) + 1, used_max - valid_gws + 1)
    train_df = work[work["gw"] < valid_start].copy()
    valid_df = work[work["gw"] >= valid_start].copy()
    return train_df, valid_df, used_max, available_max, valid_start


def fit_ridge_closed_form(train_df, feature_cols, alpha=4.0):
    x_raw = train_df[feature_cols].copy()
    x_raw = x_raw.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    medians = x_raw.median(numeric_only=True).fillna(0.0)
    x_filled = x_raw.fillna(medians).fillna(0.0)

    means = x_filled.mean()
    stds = x_filled.std(ddof=0).replace(0.0, 1.0).fillna(1.0)
    x_std = (x_filled - means) / stds

    y = pd.to_numeric(train_df["target_points"], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0).values.astype(float)

    x = x_std.values.astype(float)
    n = x.shape[0]
    x1 = np.column_stack([np.ones(n), x])

    penalty = np.eye(x1.shape[1]) * float(alpha)
    penalty[0, 0] = 0.0

    xtx = np.dot(x1.T, x1)
    xty = np.dot(x1.T, y)
    system = xtx + penalty
    try:
        beta = np.linalg.solve(system, xty)
    except Exception:
        beta = np.linalg.lstsq(system, xty, rcond=None)[0]

    model = {
        "feature_cols": feature_cols,
        "medians": medians.to_dict(),
        "means": means.to_dict(),
        "stds": stds.to_dict(),
        "intercept": float(beta[0]),
        "coefficients": {feature_cols[i]: float(beta[i + 1]) for i in range(len(feature_cols))},
        "alpha": float(alpha),
    }
    return model


def predict_with_model(model, df):
    x_raw = df[model["feature_cols"]].copy()
    x_raw = x_raw.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    medians = pd.Series(model["medians"])
    means = pd.Series(model["means"])
    stds = pd.Series(model["stds"]).replace(0.0, 1.0)

    x = x_raw.fillna(medians).fillna(0.0)
    x = (x - means) / stds

    coef = np.array([model["coefficients"][c] for c in model["feature_cols"]], dtype=float)
    pred = model["intercept"] + np.dot(x.values.astype(float), coef)
    return pred


def evaluate_predictions(df, pred_col="pred"):
    out = {}
    actual = pd.to_numeric(df["target_points"], errors="coerce").fillna(0.0)
    pred = pd.to_numeric(df[pred_col], errors="coerce").fillna(0.0)

    out["mae"] = float((pred - actual).abs().mean())
    out["rmse"] = float(np.sqrt(((pred - actual) ** 2).mean()))

    rows = []
    for gw, g in df.groupby("gw"):
        if len(g) < 10:
            continue
        corr = spearman_rank_corr(g[pred_col], g["target_points"])
        topk = 25
        pred_top = set(g.sort_values(pred_col, ascending=False).head(topk)["player_id"].astype(int).tolist())
        act_top = set(g.sort_values("target_points", ascending=False).head(topk)["player_id"].astype(int).tolist())
        overlap = len(pred_top.intersection(act_top))
        rows.append(
            {
                "gw": int(gw),
                "spearman": float(corr) if corr == corr else None,
                "top25_overlap": int(overlap),
            }
        )
    per_gw = pd.DataFrame(rows).sort_values("gw") if rows else pd.DataFrame(columns=["gw", "spearman", "top25_overlap"])
    out["per_gw"] = per_gw
    out["avg_spearman"] = float(per_gw["spearman"].mean()) if not per_gw.empty else None
    out["avg_top25_overlap"] = float(per_gw["top25_overlap"].mean()) if not per_gw.empty else None
    return out


def model_output_paths(out_dir, season, used_max_gw):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = out / f"xpts_ridge_{season}_gw{used_max_gw}"
    return {
        "model_json": str(base.with_suffix(".json")),
        "valid_csv": str(base.with_name(base.name + "_valid_predictions").with_suffix(".csv")),
        "metrics_csv": str(base.with_name(base.name + "_valid_metrics_per_gw").with_suffix(".csv")),
    }


def main():
    ap = argparse.ArgumentParser(description="Train a first xPts model from player_gw_history data.")
    ap.add_argument("--input", default="", help="Path to player_gw_history_*.csv. Defaults to latest in data/processed/fpl.")
    ap.add_argument("--train-max-gw", type=int, default=26, help="Use rows up to this GW. If unavailable, uses latest GW in data.")
    ap.add_argument("--valid-gws", type=int, default=3, help="Hold out last N GWs (within train-max-gw window) for validation.")
    ap.add_argument("--alpha", type=float, default=4.0, help="Ridge regularization strength.")
    ap.add_argument("--out-dir", default="data/models", help="Where to write model and validation artifacts.")
    args = ap.parse_args()

    path = Path(args.input) if args.input else find_latest_gw_history()
    if not path or not Path(path).exists():
        print("No input found. Provide --input or generate data with: python3 -m src.season_history --resume")
        return 2

    try:
        df = load_history(path)
    except Exception as exc:
        print(f"Failed to load input: {exc}")
        return 2

    if df.empty:
        print(f"Input is empty: {path}")
        return 2

    feat_df = add_features(df)
    feature_cols = get_feature_columns(feat_df)
    if not feature_cols:
        print("No feature columns found.")
        return 2

    try:
        train_df, valid_df, used_max, available_max, valid_start = split_train_valid(
            feat_df,
            train_max_gw=args.train_max_gw,
            valid_gws=args.valid_gws,
        )
    except Exception as exc:
        print(f"Split failed: {exc}")
        return 2

    if len(train_df) < 200:
        print(f"Not enough training rows ({len(train_df)}). Need at least 200.")
        return 2
    if valid_df.empty:
        print("Validation split is empty. Increase available GW data or lower --valid-gws.")
        return 2

    model = fit_ridge_closed_form(train_df, feature_cols, alpha=args.alpha)

    train_scored = train_df.copy()
    train_scored["pred"] = predict_with_model(model, train_scored)
    valid_scored = valid_df.copy()
    valid_scored["pred"] = predict_with_model(model, valid_scored)

    train_eval = evaluate_predictions(train_scored, pred_col="pred")
    valid_eval = evaluate_predictions(valid_scored, pred_col="pred")

    season = parse_season_label(path)
    paths = model_output_paths(args.out_dir, season, used_max)

    payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_path": str(path),
        "season": season,
        "train_max_gw_requested": int(args.train_max_gw),
        "train_max_gw_used": int(used_max),
        "train_rows": int(len(train_df)),
        "valid_rows": int(len(valid_df)),
        "valid_gw_start": int(valid_start),
        "available_max_gw_in_file": int(available_max),
        "model_type": "ridge_closed_form",
        "model": model,
        "train_metrics": {
            "mae": train_eval["mae"],
            "rmse": train_eval["rmse"],
            "avg_spearman": train_eval["avg_spearman"],
            "avg_top25_overlap": train_eval["avg_top25_overlap"],
        },
        "valid_metrics": {
            "mae": valid_eval["mae"],
            "rmse": valid_eval["rmse"],
            "avg_spearman": valid_eval["avg_spearman"],
            "avg_top25_overlap": valid_eval["avg_top25_overlap"],
        },
    }

    Path(paths["model_json"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    keep_cols = [
        "player_id",
        "gw",
        "web_name",
        "element_type",
        "target_points",
        "pred",
        "f_fixture_count",
        "f_team_diff",
        "f_opp_diff",
    ]
    valid_keep = [c for c in keep_cols if c in valid_scored.columns]
    valid_scored[valid_keep].sort_values(["gw", "pred"], ascending=[True, False]).to_csv(paths["valid_csv"], index=False)
    valid_eval["per_gw"].to_csv(paths["metrics_csv"], index=False)

    coef_table = pd.DataFrame(
        [{"feature": k, "coef": v, "abs_coef": abs(v)} for k, v in model["coefficients"].items()]
    ).sort_values("abs_coef", ascending=False)

    print(f"Input: {path}")
    print(f"Season: {season}")
    print(f"Available max GW in file: {available_max}")
    print(f"Requested train max GW: {int(args.train_max_gw)}")
    print(f"Used train max GW: {used_max}")
    if used_max < int(args.train_max_gw):
        print(f"Note: GW {int(args.train_max_gw)} not available yet in dataset. Trained through GW {used_max}.")
    print(f"Train rows: {len(train_df):,} | Valid rows: {len(valid_df):,} | Valid starts at GW {valid_start}")
    print(
        "Validation metrics: "
        f"MAE={valid_eval['mae']:.3f} RMSE={valid_eval['rmse']:.3f} "
        f"AvgSpearman={valid_eval['avg_spearman'] if valid_eval['avg_spearman'] is not None else 'n/a'} "
        f"AvgTop25Overlap={valid_eval['avg_top25_overlap'] if valid_eval['avg_top25_overlap'] is not None else 'n/a'}"
    )
    print("\nTop coefficients (absolute):")
    print(coef_table.head(10).to_string(index=False))
    print(f"\nSaved model: {paths['model_json']}")
    print(f"Saved validation predictions: {paths['valid_csv']}")
    print(f"Saved per-GW metrics: {paths['metrics_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
