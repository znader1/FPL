"""
Ship-fast spot-check for the minutes/rotation multiplier.

Runs the current-GW projection with PROJ_APPLY_MINUTES_MODEL off vs on, prints
the biggest movers, and sanity-checks direction. Eyeball the movers, then flip
config.PROJ_APPLY_MINUTES_MODEL = True.

Usage:
    .venv/bin/python -m scripts.spotcheck_minutes
"""
import pandas as pd

from src import config, fpl_client, transforms, projections

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)


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
    print(f"Projecting GW{gw} (horizon 3)...\n")

    off = _project(elements_df, fixtures, teams_short, gw, False)[
        ["id", "web_name", "team_short", "xpts_horizon"]
    ].rename(columns={"xpts_horizon": "xpts_off"})
    on = _project(elements_df, fixtures, teams_short, gw, True)[
        ["id", "web_name", "xpts_horizon", "prob_start", "minutes_mult_gw" + str(gw)]
    ].rename(columns={"xpts_horizon": "xpts_on",
                      "minutes_mult_gw" + str(gw): "mult_gw1"})

    merged = off.merge(on, on="id", how="inner")
    merged["delta"] = merged["xpts_on"] - merged["xpts_off"]
    merged["pct"] = (merged["delta"] / merged["xpts_off"].mask(merged["xpts_off"] == 0)) * 100.0

    print("=== 20 biggest DOWN movers (rotation/injury risk caught) ===")
    print(merged.sort_values("delta").head(20).to_string(index=False))

    # Sanity: relative multiplier never raises a projection.
    max_up = merged["delta"].max()
    print(f"\nMax upward move (should be ~0): {max_up:.4f}")
    assert max_up <= 1e-6, "Relative multiplier must not raise projections."
    # Sanity: someone is discounted.
    assert merged["delta"].min() < -1e-6, "Expected at least one discounted player."
    print("Spot-check assertions passed. Eyeball the movers above, then set "
          "config.PROJ_APPLY_MINUTES_MODEL = True in src/config.py.")


if __name__ == "__main__":
    main()
