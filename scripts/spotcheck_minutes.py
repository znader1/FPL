"""
Ship-fast spot-check for the minutes/rotation multiplier.

Runs the current-GW projection with PROJ_APPLY_MINUTES_MODEL off vs on, prints
the biggest movers plus a multiplier distribution, and checks the real
invariants. Whether to enable PROJ_APPLY_MINUTES_MODEL is a MANUAL decision —
review the distribution first (see the pre-season warning below).

Invariants checked here (the only ones that always hold):
  * every minutes_mult is in [0, 1];
  * at least one player is discounted (some mult < 1).
NOT an invariant: "no player's projection increases". `off` already carries the
legacy chance-of-playing discount (a different scheme than the minutes model),
and applying an in-[0,1] multiplier to a NEGATIVE baseline projection (fringe
players with negative ep_next) moves it toward zero, i.e. up. Both are expected,
so per-player off-vs-on increases are reported, not asserted against.

Usage:
    .venv/bin/python -m scripts.spotcheck_minutes
"""
import pandas as pd

from src import config, fpl_client, transforms, projections

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)


def _inputs():
    bootstrap = fpl_client.get_bootstrap()
    fixtures = transforms.fixtures_df(fpl_client.get_fixtures())
    elements_df, teams_df, _ = transforms.tables_from_bootstrap(bootstrap)
    teams_short = teams_df.set_index("id")["short_name"].to_dict()
    events = bootstrap.get("events", []) or []
    gw = next((e["id"] for e in events if e.get("is_next")), None)
    if gw is None:
        gw = next((e["id"] for e in events if not e.get("finished")), 1)
    return elements_df, fixtures, teams_short, int(gw)


def _project(elements_df, fixtures, teams_short, gw, apply_minutes):
    config.PROJ_APPLY_MINUTES_MODEL = apply_minutes
    return projections.project_elements_next_gws(
        elements_df, fixtures, teams_short, gw_start=gw, horizon_gws=3
    )


def main():
    elements_df, fixtures, teams_short, gw = _inputs()
    gws = [gw, gw + 1, gw + 2]
    print(f"Projecting GW{gw} (horizon 3)...\n")

    off = _project(elements_df, fixtures, teams_short, gw, False)
    on = _project(elements_df, fixtures, teams_short, gw, True)

    keep_off = ["id", "web_name", "team_short", "xpts_horizon"] + [f"xpts_gw{g}" for g in gws]
    keep_on = ["id", "xpts_horizon", "prob_start"] + \
        [f"xpts_gw{g}" for g in gws] + [f"minutes_mult_gw{g}" for g in gws]
    o = off[[c for c in keep_off if c in off.columns]]
    n = on[[c for c in keep_on if c in on.columns]]
    m = o.merge(n, on="id", suffixes=("_off", "_on"))
    m["delta"] = m["xpts_horizon_on"] - m["xpts_horizon_off"]

    mult_cols = [f"minutes_mult_gw{g}" for g in gws if f"minutes_mult_gw{g}" in m.columns]
    mc1 = f"minutes_mult_gw{gw}"

    print("=== 20 biggest DOWN movers (rotation/injury risk caught) ===")
    down_cols = ["web_name", "team_short", "prob_start",
                 "xpts_horizon_off", "xpts_horizon_on", "delta"] + mult_cols
    print(m.sort_values("delta")[[c for c in down_cols if c in m.columns]].head(20).to_string(index=False))

    print("\n=== 5 biggest UP movers (expected: negative-ep_next fringe scaled toward zero) ===")
    up_cols = ["web_name", "team_short", "xpts_horizon_off", "xpts_horizon_on", "delta"]
    print(m.sort_values("delta", ascending=False)[[c for c in up_cols if c in m.columns]].head(5).to_string(index=False))

    # --- distribution / pre-season thin-history detector ---
    mult1 = m[mc1]
    n_total = len(m)
    n_disc = int((mult1 < 0.95).sum())
    agg_off = float(m["xpts_horizon_off"].sum())
    agg_on = float(m["xpts_horizon_on"].sum())
    print(f"\nPlayers: {n_total} | discounted (mult_gw1<0.95): {n_disc} ({100*n_disc/max(1,n_total):.0f}%) "
          f"| median mult_gw1: {mult1.median():.3f} | min {mult1.min():.3f} / max {mult1.max():.3f}")
    print(f"Aggregate xpts_horizon: off {agg_off:.1f} -> on {agg_on:.1f} (delta {agg_on-agg_off:+.1f})")

    mode_share = float((abs(mult1 - mult1.median()) < 1e-6).mean())
    if mode_share > 0.6:
        print(
            f"\n*** PRE-SEASON WARNING: {mode_share*100:.0f}% of players share one multiplier "
            f"({mult1.median():.3f}) — this is the no-current-season-history case (everyone falls back "
            "to the start prior). The model is a near-uniform deflation, not a rotation signal yet. "
            "Do NOT enable PROJ_APPLY_MINUTES_MODEL until a few GWs of real minutes have accrued. ***"
        )

    # --- real invariants (always true) ---
    for c in mult_cols:
        assert m[c].between(0.0, 1.0).all(), f"{c} outside [0,1]"
    assert (m[mult_cols].min().min()) < 1.0, "expected at least one discounted player"
    print("\nInvariants passed: all minutes_mult in [0,1]; at least one discount applied.")
    print("Enabling PROJ_APPLY_MINUTES_MODEL is a MANUAL decision — review the distribution above.")


if __name__ == "__main__":
    main()
