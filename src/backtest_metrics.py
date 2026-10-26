"""
Pure metrics for the minutes A/B backtest. Each function takes ``frames``: a list
of per-GW DataFrames with columns: player_id, xpts (projected this GW), actual
(actual points this GW), position, minutes (actual minutes this GW).
"""
from __future__ import annotations

import pandas as pd


def _frame_universe(df, top_n):
    """Rows in the top-``top_n`` by projected xpts OR that actually played."""
    d = df.reset_index(drop=True)
    d["xpts"] = pd.to_numeric(d["xpts"], errors="coerce").fillna(0.0)
    d["actual"] = pd.to_numeric(d["actual"], errors="coerce").fillna(0.0)
    mins = pd.to_numeric(d.get("minutes", 0), errors="coerce").fillna(0.0)
    top_idx = set(d.nlargest(top_n, "xpts").index)
    played_idx = set(d.index[mins > 0])
    return d.loc[sorted(top_idx | played_idx)]


def _pooled_universe(frames, top_n):
    parts = [_frame_universe(f, top_n) for f in frames if f is not None and not f.empty]
    if not parts:
        return pd.DataFrame(columns=["player_id", "xpts", "actual", "position", "minutes"])
    return pd.concat(parts, ignore_index=True)


def projection_mae(frames, top_n=40):
    u = _pooled_universe(frames, top_n)
    if u.empty:
        return 0.0
    return float((u["xpts"] - u["actual"]).abs().mean())


def mae_by_position(frames, top_n=40):
    u = _pooled_universe(frames, top_n)
    out = {}
    for pos, g in u.groupby("position"):
        out[str(pos)] = float((g["xpts"] - g["actual"]).abs().mean())
    return out


def captain_hit_rate(frames, top_k=5):
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return 0.0
    hits = 0
    for f in frames:
        d = f.reset_index(drop=True)
        d["xpts"] = pd.to_numeric(d["xpts"], errors="coerce").fillna(0.0)
        d["actual"] = pd.to_numeric(d["actual"], errors="coerce").fillna(0.0)
        top_proj_pid = d.loc[d["xpts"].idxmax(), "player_id"]
        actual_topk = set(d.nlargest(top_k, "actual")["player_id"])
        if top_proj_pid in actual_topk:
            hits += 1
    return hits / len(frames)


def captain_regret(frames):
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return 0.0
    regrets = []
    for f in frames:
        d = f.reset_index(drop=True)
        d["xpts"] = pd.to_numeric(d["xpts"], errors="coerce").fillna(0.0)
        d["actual"] = pd.to_numeric(d["actual"], errors="coerce").fillna(0.0)
        best = float(d["actual"].max())
        picked = float(d.loc[d["xpts"].idxmax(), "actual"])
        regrets.append(best - picked)
    return float(sum(regrets) / len(regrets))


def top_n_precision(frames, n=10):
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return 0.0
    vals = []
    for f in frames:
        d = f.reset_index(drop=True)
        d["xpts"] = pd.to_numeric(d["xpts"], errors="coerce").fillna(0.0)
        d["actual"] = pd.to_numeric(d["actual"], errors="coerce").fillna(0.0)
        tp = set(d.nlargest(n, "xpts")["player_id"])
        ta = set(d.nlargest(n, "actual")["player_id"])
        vals.append(len(tp & ta) / n)
    return float(sum(vals) / len(vals))


# ---------------------------------------------------------------- calibration
# Frames for these carry: player_id, position, price_m, xpts, actual, minutes,
# had_fixture. Population = player-GWs whose team had a fixture (benched and
# zero-minute rows included, since projections carry minutes risk); the *_app
# columns repeat the numbers over appearances only (minutes > 0).

PRICE_BANDS = ("<6", "6-8", "8+")
BAND_BIAS_MIN_N = 20


def price_band(price_m):
    p = float(price_m)
    if p < 6.0:
        return "<6"
    if p < 8.0:
        return "6-8"
    return "8+"


def _cell_stats(g):
    err = g["xpts"] - g["actual"]
    app = g[g["minutes"] > 0]
    app_err = app["xpts"] - app["actual"]
    spearman = None
    if len(g) >= 3:
        corr = g["xpts"].rank().corr(g["actual"].rank())
        spearman = None if pd.isna(corr) else float(corr)
    return {
        "n": int(len(g)),
        "mae": float(err.abs().mean()),
        "bias": float(err.mean()),
        "spearman": spearman,
        "n_app": int(len(app)),
        "mae_app": float(app_err.abs().mean()) if len(app) else None,
        "bias_app": float(app_err.mean()) if len(app) else None,
    }


def calibration_table(frames):
    parts = [f for f in frames if f is not None and not f.empty]
    cols = ["pos", "band", "n", "mae", "bias", "spearman", "mae_app", "bias_app", "n_app"]
    if not parts:
        return pd.DataFrame(columns=cols)
    d = pd.concat(parts, ignore_index=True)
    d = d[d["had_fixture"].astype(bool)].copy()
    if d.empty:
        return pd.DataFrame(columns=cols)
    for c in ("xpts", "actual", "minutes", "price_m"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0)
    d["band"] = d["price_m"].map(price_band)
    rows = []
    for (pos, band), g in d.groupby(["position", "band"]):
        rows.append({"pos": str(pos), "band": band, **_cell_stats(g)})
    rows.append({"pos": "ALL", "band": "ALL", **_cell_stats(d)})
    return pd.DataFrame(rows)[cols]


def band_bias(table, min_n=BAND_BIAS_MIN_N):
    """Mean |bias| over (pos, band) cells with n >= min_n, excluding ALL."""
    t = table[(table["pos"] != "ALL") & (table["n"] >= min_n)]
    if t.empty:
        return 0.0
    return float(t["bias"].abs().mean())
