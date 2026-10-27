"""Key-player absence analysis: does a team's attacking output move when a
key player is missing? Monitoring tool for the owner, nothing user-facing.

    PYTHONPATH=. python -m scripts.analyze_key_absence --season 2025-26
    PYTHONPATH=. python -m scripts.analyze_key_absence --season 2026-27 --refresh
    PYTHONPATH=. python -m scripts.analyze_key_absence --season 2026-27 \
        --key-players "CHE:João Pedro,Palmer,Rogers"

Writes data/backtest/key_absence_<season>.csv, data/backtest/key_absence_teammates_<season>.csv
and docs/key_absence_<season>_<date>.md. Design:
docs/superpowers/specs/2026-10-27-key-absence-analysis-design.md
"""
import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from src import fixture_difficulty as fd
from src import fpl_client, key_absence, live_history

LAST_SEASON = "2025-26"
NO_DECAY_HALFLIFE_DAYS = 1e6


def _history_path(season):
    return Path("data/processed/fpl") / season / f"player_match_history_{season}.csv"


def _raw_dir(season):
    return Path("data/raw/fpl") / season


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _fetch_and_cache(season):
    """Live bootstrap + fixtures for the current season, cached under data/raw."""
    raw = _raw_dir(season)
    raw.mkdir(parents=True, exist_ok=True)
    bootstrap = fpl_client.get_bootstrap()
    fixtures = fpl_client.get_fixtures()
    (raw / "bootstrap_static.json").write_text(json.dumps(bootstrap))
    (raw / "fixtures.json").write_text(json.dumps(fixtures))
    return bootstrap, fixtures


def _refresh(season, bootstrap, fixtures):
    path = _history_path(season)
    existing = pd.read_csv(path) if path.exists() else None
    missing = live_history.missing_event_ids(existing, bootstrap)
    if not missing:
        print("history already current")
        return
    updated, added = live_history.append_events(existing, bootstrap, fixtures, missing)
    if updated.empty:
        print("refresh returned no rows")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    updated.to_csv(path, index=False)
    print(f"appended {added}")


def _ratings(df, season, teams_short_map):
    team_xg = fd.build_team_match_xg(df)
    if season == LAST_SEASON:
        return fd.compute_team_ratings(team_xg, halflife_days=NO_DECAY_HALFLIFE_DAYS, shrinkage_matches=0)
    return fd.resolve_team_ratings(team_xg, teams_short_map=teams_short_map,
                                   halflife_days=NO_DECAY_HALFLIFE_DAYS)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", required=True)
    ap.add_argument("--refresh", action="store_true", help="append finished GWs via /event/{gw}/live/ (current season)")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--key-players", default=None, help='e.g. "CHE:João Pedro,Palmer;ARS:Saka"')
    ap.add_argument("--out-dir", default="data/backtest")
    ap.add_argument("--docs-dir", default="docs")
    args = ap.parse_args(argv)
    season = args.season
    is_last = season == LAST_SEASON

    if is_last:
        bootstrap = _load_json(_raw_dir(season) / "bootstrap_static.json")
        fixtures = _load_json(_raw_dir(season) / "fixtures.json")
    else:
        bootstrap, fixtures = _fetch_and_cache(season)
        if args.refresh:
            _refresh(season, bootstrap, fixtures)

    raw_df = pd.read_csv(_history_path(season))
    df = key_absence.normalize_history(raw_df, fixtures)
    teams_short_map = {int(t["id"]): t["short_name"] for t in bootstrap["teams"]}
    names = {int(e["id"]): e["web_name"] for e in bootstrap["elements"]}

    if is_last:
        signals = key_absence.build_signals_from_history(raw_df)
    else:
        last_raw = _raw_dir(LAST_SEASON)
        last_path = _history_path(LAST_SEASON)
        last_df = pd.read_csv(last_path) if last_path.exists() else None   # raw: element, minutes, total_points
        if last_df is not None:
            last_df["minutes"] = pd.to_numeric(last_df["minutes"], errors="coerce").fillna(0.0)
        last_boot_path = last_raw / "bootstrap_static.json"
        last_boot = _load_json(last_boot_path) if last_boot_path.exists() else None
        signals = key_absence.build_signals(df, bootstrap, last_df, last_boot)

    overrides = key_absence.parse_overrides(args.key_players, bootstrap, teams_short_map)
    key = key_absence.select_key_players(signals, top=args.top, overrides=overrides)
    placebo = key_absence.select_placebo(df, key, key_absence.team_fixture_sets(df))
    ratings = _ratings(df, season, teams_short_map)

    result = key_absence.run_analysis(df, fixtures, ratings, key, placebo, teams_short_map, names)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(result["team_rows"] + [dict(r, placebo=True) for r in result["placebo_rows"]]) \
        .to_csv(out_dir / f"key_absence_{season}.csv", index=False)
    pd.DataFrame(result["teammate_rows"]).to_csv(out_dir / f"key_absence_teammates_{season}.csv", index=False)

    caveats = [
        "Absence is inferred: a key player with no row (or zero minutes) for a fixture his team played.",
        "Transferred players are bounded to their first appearance for the club; the window closes only when they later play for another club.",
        "Per-team n is small; read the shrunk column (toward the league pool, k=4) before the raw one.",
        "Expected xG controls for opponent defence and venue via the production ratings path "
        + ("(no carryover seed for 2025-26: live-only, no shrinkage)." if is_last else "(2025-26 seed + this season, no decay)."),
    ]
    if is_last:
        caveats.append("2025-26 selection uses season totals from the same matches (identical for every player, noted).")
    report = key_absence.render_report(result, season, key, names, teams_short_map, caveats)
    docs = Path(args.docs_dir)
    docs.mkdir(parents=True, exist_ok=True)
    report_path = docs / f"key_absence_{season}_{date.today().isoformat()}.md"
    report_path.write_text(report)

    kp, pp = result["key_pool"], result["placebo_pool"]
    ok, why = result["decision"]
    print(f"{season}: key {kp['effect']:.3f} [{kp['lo']:.3f}, {kp['hi']:.3f}] n={kp['n']:.0f} pairs={kp['pairs']} "
          f"| placebo {pp['effect']:.3f} n={pp['n']:.0f} | {'PASS' if ok else 'FAIL'}: {why}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
