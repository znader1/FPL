#!/usr/bin/env python3
"""
Dry-run the 2026-27 (or any new) season cold start before real fixtures exist.

Simulates exactly what happens when FPL resets in the summer:
  * the 3 relegated teams (computed from last season's results) drop out,
  * 3 promoted teams arrive with no top-flight xG,
  * every team gets a NEW FPL id (we shuffle ids on purpose to prove the
    short-name keyed carryover survives the reshuffle),
  * there is zero current-season match history,
  * fixtures are synthetic (round-robin) until the real list drops.

It then resolves carryover ratings, applies the knowledge discount, builds the
GW1-N ticker, and prints what users would see in July.

Usage:
  python3 scripts/simulate_new_season.py
  python3 scripts/simulate_new_season.py --promoted "LEI,SOU,WBA" --horizon 6
  python3 scripts/simulate_new_season.py --out data/processed/sim_ticker.json

Once real 2026-27 fixtures exist (June 19), stop using this and point the app
at the real bootstrap/fixtures; everything downstream behaves identically.
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src import fixture_difficulty as fd  # noqa: E402


def final_table_from_results(fixtures_path, bootstrap_path):
    """Compute last season's final standings (points) from fixture results."""
    with open(bootstrap_path) as f:
        boot = json.load(f)
    short = {int(t["id"]): t["short_name"] for t in boot.get("teams", [])}

    with open(fixtures_path) as f:
        fixtures = json.load(f)

    points = {tid: 0 for tid in short}
    played = {tid: 0 for tid in short}
    for fx in fixtures:
        if not fx.get("finished"):
            continue
        h, a = fx.get("team_h"), fx.get("team_a")
        hs, as_ = fx.get("team_h_score"), fx.get("team_a_score")
        if h is None or a is None or hs is None or as_ is None:
            continue
        h, a = int(h), int(a)
        played[h] = played.get(h, 0) + 1
        played[a] = played.get(a, 0) + 1
        if hs > as_:
            points[h] = points.get(h, 0) + 3
        elif hs < as_:
            points[a] = points.get(a, 0) + 3
        else:
            points[h] = points.get(h, 0) + 1
            points[a] = points.get(a, 0) + 1

    table = sorted(short, key=lambda t: points.get(t, 0), reverse=True)
    return [(short[t], points.get(t, 0), played.get(t, 0)) for t in table]


def round_robin_fixtures(team_ids, n_gws, seed=42):
    """
    Synthetic single-round-robin schedule (circle method) for n_gws GWs.
    Returns a fixtures DataFrame with event/team_h/team_a columns matching
    what transforms.fixtures_by_team_for_gw expects.
    """
    rng = random.Random(seed)
    teams = list(team_ids)
    rng.shuffle(teams)
    n = len(teams)
    assert n % 2 == 0, "need an even number of teams"

    rows = []
    rotation = teams[1:]
    for gw in range(1, n_gws + 1):
        order = [teams[0]] + rotation
        for i in range(n // 2):
            home, away = order[i], order[n - 1 - i]
            if gw % 2 == 0:  # alternate venues a bit
                home, away = away, home
            rows.append({"event": gw, "team_h": home, "team_a": away, "finished": False})
        rotation = rotation[-1:] + rotation[:-1]
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season-label", default="2026-27")
    ap.add_argument("--promoted", default="PRO1,PRO2,PRO3",
                    help="Comma-separated short names of the 3 promoted teams "
                         "(e.g. 'LEI,SOU,WBA'). Placeholders are fine pre-June-19.")
    ap.add_argument("--horizon", type=int, default=6)
    ap.add_argument("--fixtures", default="data/raw/fpl/2025-26/fixtures.json")
    ap.add_argument("--bootstrap", default="data/raw/fpl/2025-26/bootstrap_static.json")
    ap.add_argument("--seed-path", default=None, help="Carryover seed (default: config path)")
    ap.add_argument("--id-shuffle-seed", type=int, default=7,
                    help="Random seed for the fake FPL team-id reshuffle")
    ap.add_argument("--out", default=None, help="Optional path to write the ticker JSON")
    args = ap.parse_args()

    promoted = [s.strip().upper() for s in args.promoted.split(",") if s.strip()]
    if len(promoted) != 3:
        print("ERROR: exactly 3 promoted teams required.")
        return 1

    # 1. Last season's final table -> bottom 3 relegated.
    table = final_table_from_results(args.fixtures, args.bootstrap)
    relegated = [t[0] for t in table[-3:]]
    survivors = [t[0] for t in table[:-3]]
    print(f"=== {args.season_label} simulation ===")
    print(f"Relegated (from final table): {', '.join(relegated)}")
    print(f"Promoted (assumed): {', '.join(promoted)}")

    # 2. New season team set with RESHUFFLED ids (like FPL does every July).
    new_shorts = survivors + promoted
    rng = random.Random(args.id_shuffle_seed)
    new_ids = list(range(1, len(new_shorts) + 1))
    rng.shuffle(new_ids)
    teams_short_map = {tid: short for tid, short in zip(new_ids, new_shorts)}

    # 3. Cold start: NO current-season xG. Carryover seed + promoted defaults.
    empty_xg = pd.DataFrame()
    ratings = fd.resolve_team_ratings(empty_xg, teams_short_map=teams_short_map,
                                      seed_path=args.seed_path)
    ratings = fd.apply_knowledge_discount(ratings, teams_short_map=teams_short_map)

    sources = {}
    for tid, r in ratings.items():
        if tid == "_league" or not isinstance(r, dict):
            continue
        sources[r.get("source", "?")] = sources.get(r.get("source", "?"), 0) + 1
    print(f"Rating sources: {sources} (expect 17 carryover / 3 promoted)")

    rt = fd.team_ratings_table(ratings)
    rt["short"] = rt["team_id"].map(teams_short_map)
    print("\nStrongest attacks:",
          ", ".join(f"{r.short} {r.attack:.2f}" for r in rt.head(5).itertuples()))
    best_def = rt.sort_values("defense").head(5)
    print("Best defenses:   ",
          ", ".join(f"{r.short} {r.defense:.2f}" for r in best_def.itertuples()))
    promoted_rows = rt[rt["short"].isin(promoted)]
    print("Promoted teams:  ",
          ", ".join(f"{r.short} atk={r.attack:.2f} def={r.defense:.2f}"
                    for r in promoted_rows.itertuples()))

    # 4. Synthetic round-robin fixtures until the real list exists.
    fixtures = round_robin_fixtures(list(teams_short_map.keys()), args.horizon)

    # 5. Ticker — exactly what /fixtures/difficulty will serve.
    ticker = fd.build_fixture_ticker(ratings, fixtures, teams_short_map, 1,
                                     horizon_gws=args.horizon)
    print(f"\n=== GW1-{args.horizon} ticker (synthetic fixtures) ===")
    print(f"Easiest runs: {' > '.join(ticker['easiest_runs'])}")
    print(f"Hardest runs: {' > '.join(ticker['hardest_runs'])}")
    print(f"\n{'Team':<6} {'Avg':<5} " + " ".join(f"GW{g:<8}" for g in ticker["gws"]))
    for t in ticker["teams"]:
        cells = []
        for gw in ticker["gws"]:
            cell = t["gws"][gw]
            if cell["blank"] or not cell["opponents"]:
                cells.append("—".ljust(10))
            else:
                o = cell["opponents"][0]
                cells.append(f"{o['opp_short']}({'H' if o['home'] else 'A'}){o['difficulty']:.1f}".ljust(10))
        print(f"{t['team_short']:<6} {t['avg_difficulty']:<5.2f} " + "".join(cells))

    if args.out:
        out_fp = Path(args.out)
        out_fp.parent.mkdir(parents=True, exist_ok=True)
        out_fp.write_text(json.dumps(ticker, indent=2, default=str))
        print(f"\nTicker JSON written to {args.out}")

    print("\nNext steps: replace --promoted with the real 3 on confirmation, and "
          "swap synthetic fixtures for the real list on June 19.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
