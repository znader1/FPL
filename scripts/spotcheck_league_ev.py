"""
Spot-check for ownership-adjusted EV ranking.

For a sample entry+league, prints the legacy raw-xPts top-10 vs the differential-EV
top-10 side by side, plus the captain-differential result. Review that highly
league-owned premiums drop and genuine low-owned differentials rise.

Usage:
    .venv/bin/python -m scripts.spotcheck_league_ev <entry_id> <league_id> [event_id]
"""
import sys

from src import config, fpl_client, transforms, projections, league_strategy


def main():
    if len(sys.argv) < 3:
        print("usage: python -m scripts.spotcheck_league_ev <entry_id> <league_id> [event_id]")
        return
    entry_id, league_id = int(sys.argv[1]), int(sys.argv[2])
    bootstrap = fpl_client.get_bootstrap()
    fixtures = transforms.fixtures_df(fpl_client.get_fixtures())
    elements_df, teams_df, _ = transforms.tables_from_bootstrap(bootstrap)
    teams_short = teams_df.set_index("id")["short_name"].to_dict()
    events = bootstrap.get("events", []) or []
    gw = int(sys.argv[3]) if len(sys.argv) > 3 else (
        next((e["id"] for e in events if e.get("is_next")), None)
        or next((e["id"] for e in events if not e.get("finished")), 1))

    proj = projections.project_elements_next_gws(elements_df, fixtures, teams_short, gw_start=gw, horizon_gws=3)
    analysis = league_strategy.analyze_league(entry_id, league_id, gw)
    if analysis.get("error"):
        print("analyze_league error:", analysis["error"])
        return
    meta = league_strategy._player_meta(bootstrap, projections_df=proj)
    templates = league_strategy.ownership_ev.compute_position_templates(meta)

    def top10(mode, flag):
        config.LEAGUE_EV_RANKING = flag
        rows = league_strategy._candidate_targets(analysis, meta, mode, templates)
        return [(r.get("web_name"), r.get("league_ownership"),
                 r.get("model_xpts_horizon"), r.get("differential_ev")) for r in rows]

    for mode in ("chase", "defend", "differential"):
        print(f"\n===== mode: {mode} =====")
        legacy = top10(mode, False)
        ev = top10(mode, True)
        print(f"{'LEGACY (raw xPts)':38} | EV (differential)")
        for i in range(max(len(legacy), len(ev))):
            l = legacy[i] if i < len(legacy) else ("", "", "", "")
            e = ev[i] if i < len(ev) else ("", "", "", "")
            print(f"{str(l[0]):20} own={str(l[1]):6} xpts={str(l[2]):6} | "
                  f"{str(e[0]):20} own={str(e[1]):6} ev={str(e[3]):6}")

    from src import fixture_difficulty  # ticker for captain differential, best-effort
    ticker = None
    try:
        match_df = fixture_difficulty.load_match_history()
        team_match_xg = fixture_difficulty.build_team_match_xg(match_df)
        ratings = fixture_difficulty.resolve_team_ratings(team_match_xg, teams_short_map=teams_short)
        ratings = fixture_difficulty.apply_knowledge_discount(ratings, teams_short_map=teams_short)
        ticker = fixture_difficulty.build_fixture_ticker(ratings, fixtures, teams_short, gw, horizon_gws=3)
    except Exception as exc:
        print(f"\n(ticker unavailable: {exc})")
    cap = league_strategy.detect_captain_differential(analysis, meta, templates, ticker)
    print("\n===== captain_differential =====")
    print(cap.get("reason") if cap else "none")


if __name__ == "__main__":
    main()
