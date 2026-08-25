"""
Is the xG blend adding skill, or just shrinking predictions?

MAE rewards shrinkage: because most players score 0-2 points, a model that
predicts lower for everyone lowers mean absolute error without ordering players
any better. The blend sweep showed MAE improving while top-10 precision got
worse, which is exactly that signature — so before acting on the MAE win, check
the scale-free measure.

Spearman rank correlation against actual points answers it directly: it ignores
scale entirely and only asks whether the ranking improved. If MAE improves and
rank correlation doesn't, the gain is shrinkage and not worth shipping.

    PYTHONPATH=. .venv/bin/python -m scripts.backtest_blend_diagnose
"""
import argparse

import pandas as pd

from src import backtest_data
from scripts.backtest_blend_sweep import _frame_for_gw, _team_name_to_id

DEFAULT_WEIGHTS = [0.0, 0.25, 0.5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=None)
    ap.add_argument("--min-gw", type=int, default=6)
    ap.add_argument("--max-gws", type=int, default=None)
    args = ap.parse_args()

    weights = ([float(w) for w in args.weights.split(",")] if args.weights else DEFAULT_WEIGHTS)
    gws = [g for g in backtest_data.available_gws() if g >= args.min_gw]
    if args.max_gws:
        gws = gws[: args.max_gws]

    name_to_id = _team_name_to_id()
    print(f"Blend diagnostics — GW{min(gws)}..GW{max(gws)} ({len(gws)} GWs)\n")
    print(f"{'weight':>7} {'mean pred':>10} {'mean act':>9} {'sd pred':>8} "
          f"{'sd act':>7} {'spearman':>9} {'top10 recall':>13}")

    for w in weights:
        frames = []
        for gw in gws:
            try:
                frames.append(_frame_for_gw(gw, w, name_to_id))
            except Exception:
                pass
        if not frames:
            continue

        rhos, recalls = [], []
        for f in frames:
            # Restrict to players who actually featured: the full pool is
            # dominated by non-playing squad filler, which flatters any model
            # that predicts near-zero.
            played = f[f["minutes"] > 0]
            if len(played) < 20:
                continue
            # Spearman is Pearson on ranks; computing it that way avoids pulling
            # scipy into the backend just for this diagnostic.
            rhos.append(played["xpts"].rank().corr(played["actual"].rank()))
            top_pred = set(played.nlargest(10, "xpts")["player_id"])
            top_act = set(played.nlargest(10, "actual")["player_id"])
            recalls.append(len(top_pred & top_act) / 10.0)

        allrows = pd.concat(frames, ignore_index=True)
        played_all = allrows[allrows["minutes"] > 0]
        print(f"{w:7.2f} {played_all['xpts'].mean():10.3f} {played_all['actual'].mean():9.3f} "
              f"{played_all['xpts'].std():8.3f} {played_all['actual'].std():7.3f} "
              f"{pd.Series(rhos).mean():9.4f} {pd.Series(recalls).mean():13.3f}")

    print("\nRead: if mean pred falls toward mean act while spearman is flat, the MAE")
    print("gain is shrinkage, not skill. A real improvement raises spearman.")


if __name__ == "__main__":
    main()
