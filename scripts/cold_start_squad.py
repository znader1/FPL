#!/usr/bin/env python3
"""
Cold-start initial squad draft for a brand-new FPL season (e.g. 2026-27).

Pre-season, FPL's live bootstrap RETAINS last-season season-aggregate stats on
each element (points_per_game, total_points, expected_goals/assists, minutes),
while form/event_points reset to 0. So the projection baseline
(PPG_WEIGHT*ppg + FORM_WEIGHT*form) already carries a real, differentiated
last-season signal straight from the live API — no CSV carryover needed.

This reproduces the production wildcard-draft path against live data with the
budget forced to £100.0m and no existing squad. The pipeline itself
(availability filter, cold-start ppg-shrink, projections, wildcard-score
optimizer, lineup selection) lives in `src/squad_draft.py::build_squad` — this
script is a thin CLI wrapper: it fetches live bootstrap/fixtures, calls the
shared core, and prints a human-readable draft report.

Local analysis tool only — not wired into the product.

Usage:
  PYTHONPATH=. python3 scripts/cold_start_squad.py
  PYTHONPATH=. python3 scripts/cold_start_squad.py --horizon 5 --budget 100.0
  PYTHONPATH=. python3 scripts/cold_start_squad.py --out data/processed/cold_start.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src import fpl_client, squad_draft, transforms  # noqa: E402


def _num(df, col, default=0.0):
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=5, help="planning horizon in GWs")
    ap.add_argument("--budget", type=float, default=100.0)
    ap.add_argument("--minutes-prior", type=float, default=500.0,
                    help="pseudo-minutes K for shrinking last-season ppg toward 0 "
                         "(reliability weight = minutes/(minutes+K); guards vs small-sample mirages)")
    ap.add_argument("--min-fwd-minutes", type=float, default=0.0,
                    help="drop forwards below this last-season minutes floor from the pool "
                         "(e.g. 1500 forces a balanced build with 3 real playing forwards "
                         "instead of Haaland + cheap fodder)")
    ap.add_argument("--out", default=None, help="optional JSON dump path")
    args = ap.parse_args()

    boot = fpl_client.get_bootstrap()
    raw_fx = fpl_client.get_fixtures()

    res = squad_draft.build_squad(boot, raw_fx, {
        "horizon_gws": args.horizon,
        "budget_m": args.budget,
        "minutes_prior_k": args.minutes_prior,
        "min_fwd_minutes": args.min_fwd_minutes,
    })
    if not res["ok"]:
        print(f"DRAFT FAILED: {res['reason']}")
        return 1

    gw_start = res["gw_start"]
    horizon = res["horizon_gws"]
    gws = list(range(gw_start, gw_start + horizon))

    # Transformed elements, for display-only fields the core doesn't return:
    # raw (unshrunk) last-season ppg/minutes, full pool size, flagged-out exclusions.
    elements, _teams, _etypes = transforms.tables_from_bootstrap(boot)
    status = elements.get("status", pd.Series("a", index=elements.index)).astype(str)
    flagged_out = status.isin(squad_draft.UNAVAILABLE_STATUSES)
    K = max(1.0, float(args.minutes_prior))

    print(f"=== Cold-start draft — GW{gw_start}-{gws[-1]} (horizon {horizon}) ===")
    print(f"Pool: {len(elements) - int(flagged_out.sum())}/{len(elements)} players available "
          f"(dropped {int(flagged_out.sum())} flagged status {sorted(squad_draft.UNAVAILABLE_STATUSES)}) "
          f"| ppg minutes-prior K={int(K)}")

    # --- assemble display frame from the core's squad records ---
    view = pd.DataFrame(res["squad"])
    # raw last-season ppg + minutes for display (res["squad"].points_per_game carries the shrunk ppg)
    raw_stats = elements[["id", "minutes"]].copy()
    raw_stats["raw_ppg"] = pd.to_numeric(elements.get("points_per_game"), errors="coerce").fillna(0.0)
    raw_stats["minutes"] = pd.to_numeric(raw_stats["minutes"], errors="coerce").fillna(0.0)
    view = view.merge(raw_stats, left_on="player_id", right_on="id", how="left", suffixes=("", "_raw"))
    for c in ["price_m", "raw_ppg", "minutes", "xpts_horizon", f"xpts_gw{gw_start}", "wildcard_score"]:
        if c in view.columns:
            view[c] = pd.to_numeric(view[c], errors="coerce").fillna(0.0)

    cap_id = res["captain_player_id"]
    vice_id = res["vice_player_id"]
    xi_ids = {int(r["player_id"]) for r in res["starting_xi"]}

    pos_order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    view["_po"] = view["pos"].map(pos_order).fillna(9)
    view = view.sort_values(["_po", "xpts_horizon"], ascending=[True, False])

    total_cost = float(res["squad_cost_m"])
    print(f"\nSquad cost £{total_cost:.1f}m | bank £{args.budget - total_cost:.1f}m "
          f"| formation {res['formation'] if res['formation'] else '?'}")
    if res["formation"]:
        cap = view[view["player_id"] == cap_id]["web_name"].iloc[0] if cap_id in view["player_id"].values else cap_id
        vice = view[view["player_id"] == vice_id]["web_name"].iloc[0] if vice_id in view["player_id"].values else vice_id
        print(f"Captain: {cap}  |  Vice: {vice}")

    print(f"\n{'':3}{'Player':<16}{'Pos':<5}{'Team':<6}{'£m':>6}{'25/26 ppg':>11}{'mins':>7}{'5GW xPts':>10}{'GW1':>7}  role")
    for r in view.itertuples():
        pid = int(r.player_id)
        mark = "   "
        if pid == cap_id:
            mark = "(C)"
        elif pid == vice_id:
            mark = "(V)"
        role = "XI" if pid in xi_ids else "bench"
        gw1 = getattr(r, f"xpts_gw{gw_start}", 0.0)
        print(f"{mark:3}{r.web_name:<16}{r.pos:<5}{r.team_short:<6}"
              f"{r.price_m:>6.1f}{r.raw_ppg:>11.1f}{int(r.minutes):>7}{r.xpts_horizon:>10.1f}{gw1:>7.2f}  {role}")

    # --- notable exclusions (flagged-out players who'd otherwise be strong) ---
    excl = elements[flagged_out].copy()
    excl["ppg"] = _num(excl, "points_per_game")
    excl["price_m"] = _num(excl, "price_m", 0.0)
    excl = excl[excl["ppg"] >= 4.0].sort_values("ppg", ascending=False)
    if not excl.empty:
        print(f"\nNotable players excluded (flagged out — override manually if you disagree):")
        for r in excl.head(12).itertuples():
            news = str(getattr(r, "news", "") or "").strip()
            print(f"  {r.web_name:<16}{r.pos:<5}{r.team_short:<5}£{r.price_m:>4.1f} "
                  f"ppg {r.ppg:.1f}  status={r.status}  {news[:60]}")

    if args.out:
        out = {
            "gw_start": gw_start, "horizon": horizon,
            "budget_m": args.budget, "squad_cost_m": round(total_cost, 1),
            "formation": res["formation"],
            "captain_id": cap_id, "vice_id": vice_id,
            "squad": view[["player_id", "web_name", "pos", "team_short", "price_m",
                           "points_per_game", "xpts_horizon"]].to_dict("records"),
        }
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(out, indent=2, default=str))
        print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
