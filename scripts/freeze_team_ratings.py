#!/usr/bin/env python3
"""
Freeze end-of-season xG team ratings into a carryover seed for next season.

At a new season's launch there is no current-season xG, so the fixture-difficulty
model needs a prior. This script computes full-season attack/defense ratings from
the processed ``player_match_history`` and writes them keyed by team short name
(stable across seasons) to a seed JSON that ``fixture_difficulty.resolve_team_ratings``
reads at season start.

Usage:
  python3 scripts/freeze_team_ratings.py --season 2025-26
  python3 scripts/freeze_team_ratings.py --season 2025-26 \
      --out data/models/team_ratings_2025-26.json
"""
import argparse
import json
import sys
from pathlib import Path

# Allow `from src import ...` when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import fixture_difficulty as fd  # noqa: E402


def _teams_short_map_from_bootstrap(path):
    with open(path) as f:
        boot = json.load(f)
    return {int(t["id"]): t["short_name"] for t in boot.get("teams", [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--match-history", default=None,
                    help="player_match_history CSV (default: latest under --base-dir)")
    ap.add_argument("--base-dir", default="data/processed/fpl")
    ap.add_argument("--bootstrap", default=None,
                    help="bootstrap_static.json for team short names "
                         "(default: data/raw/fpl/<season>/bootstrap_static.json)")
    ap.add_argument("--out", default=None,
                    help="Output seed path (default: config.FDR_RATINGS_SEED_PATH)")
    ap.add_argument("--halflife-days", type=float, default=10000.0,
                    help="Decay half-life; default ~flat so the seed reflects the "
                         "whole season evenly rather than just the run-in.")
    args = ap.parse_args()

    match_df = fd.load_match_history(path=args.match_history, base_dir=args.base_dir)
    if match_df.empty:
        print("ERROR: no match history found; nothing to freeze.")
        return 1

    team_match_xg = fd.build_team_match_xg(match_df)
    asof = None
    if "kickoff_time" in team_match_xg.columns and not team_match_xg.empty:
        asof = team_match_xg["kickoff_time"].max()
    ratings = fd.compute_team_ratings(team_match_xg, asof=asof, halflife_days=args.halflife_days)

    bootstrap_path = args.bootstrap or f"data/raw/fpl/{args.season}/bootstrap_static.json"
    if not Path(bootstrap_path).exists():
        print(f"ERROR: bootstrap not found at {bootstrap_path} (need team short names).")
        return 1
    teams_short_map = _teams_short_map_from_bootstrap(bootstrap_path)

    from src import config
    out_path = args.out or getattr(config, "FDR_RATINGS_SEED_PATH",
                                   "data/models/team_ratings_seed.json")
    payload = fd.freeze_ratings(ratings, teams_short_map, out_path, season=args.season)

    n = len(payload.get("teams", {}))
    print(f"Froze {n} team ratings (season {args.season}, league_avg_xg="
          f"{payload.get('league_avg_xg')}) -> {out_path}")
    ranked = sorted(payload["teams"].items(), key=lambda kv: kv[1]["attack"], reverse=True)
    print("Top attack:", ", ".join(f"{k} {v['attack']}" for k, v in ranked[:5]))
    print("Top defense (lowest=best):",
          ", ".join(f"{k} {v['defense']}" for k, v in sorted(
              payload["teams"].items(), key=lambda kv: kv[1]["defense"])[:5]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
