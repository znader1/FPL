"""Weekly prediction-vs-actual report (calibration spec, part 6). Internal only.

    PYTHONPATH=. .venv/bin/python -m scripts.monitor_report --csv data/replay/snapshots_2026-27.csv
    PYTHONPATH=. .venv/bin/python -m scripts.monitor_report            # reads Supabase
Env for Supabase: SUPABASE_URL, SUPABASE_SERVICE_KEY.

Per model version: per-GW MAE / bias / rank correlation / captain hit rate and the
cumulative position x price-band table. When shadow rows exist, the current
model on runner data (runner_xpts) is compared with the previous model
(shadow_xpts) on the same GWs and the rollback rule gives its verdict.
"""
from __future__ import annotations

import argparse
import os

import pandas as pd
import requests

from src import backtest_metrics as bm
from src import monitoring

COLUMNS = ("season,gw,player_id,pos,price_m,model_xpts,model_version,runner_xpts,shadow_xpts,"
           "shadow_model_version,actual_points,actual_minutes")


def load_rows(csv_path=None, season="2026-27"):
    if csv_path:
        return pd.read_csv(csv_path)
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    r = requests.get(
        f"{url}/rest/v1/player_gw_snapshots?select={COLUMNS}&season=eq.{season}&limit=100000",
        headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=60)
    r.raise_for_status()
    return pd.DataFrame(r.json())


def _gw_lines(frames):
    for f in frames:
        s = monitoring.summarize([f])
        t = s["table"]
        all_row = t[t["pos"] == "ALL"].iloc[0]
        hit = bm.captain_hit_rate([f])
        print(f"  GW{int(f['gw'].iloc[0])}: MAE {s['mae']:.3f}  bias {all_row['bias']:+.3f}  "
              f"rank corr {all_row['spearman'] if all_row['spearman'] is not None else float('nan'):.3f}  "
              f"band bias {s['band_bias']:.3f}  captain pick in actual top 5: {'yes' if hit else 'no'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    ap.add_argument("--season", default="2026-27")
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    rows = load_rows(args.csv, args.season)
    if "pos" not in rows.columns:
        # Older CSV exports lack pos: take it from the live bootstrap.
        from api import main as api_main
        boot = api_main.get_bootstrap_cached()
        types = {t["id"]: t["singular_name_short"] for t in boot["element_types"]}
        pos = {e["id"]: types.get(e["element_type"]) for e in boot["elements"]}
        rows["pos"] = rows["player_id"].map(pos)
    if "model_version" not in rows.columns:
        rows["model_version"] = None
    rows["model_version"] = rows["model_version"].fillna("unversioned")

    # The local per-GW history gives the true "team had a fixture" population (the
    # replay's); without it, played-or-projected stands in for it.
    from src import projections
    hist_path = projections.find_latest_gw_history()
    history = pd.read_csv(hist_path) if hist_path else None
    print(f"population: {'team had a fixture (local history)' if history is not None else 'played or projected > 0.5 (no local history)'}\n")

    for version, vrows in rows.groupby("model_version", sort=False):
        frames = monitoring.frames_from_snapshots(vrows, "model_xpts", history)
        if not frames:
            continue
        print(f"=== live model {version} · {len(frames)} finished GWs")
        _gw_lines(frames)
        print(monitoring.summarize(frames)["table"].round(3).to_string(index=False))
        print()

    verdicts = monitoring.shadow_verdicts(rows, history) if "shadow_xpts" in rows.columns else {}
    if not verdicts:
        print("No shadow rows yet — verdict: wait")
    for version, v in verdicts.items():
        print(f"=== current vs previous model {version} on the same runner data · {v['gws']} finished GWs")
        print(f"current MAE {v['live']['mae']:.3f} band bias {v['live']['band_bias']:.3f} | "
              f"previous MAE {v['shadow']['mae']:.3f} band bias {v['shadow']['band_bias']:.3f}")
        print(f"verdict: {v['verdict']}")

if __name__ == "__main__":
    main()
