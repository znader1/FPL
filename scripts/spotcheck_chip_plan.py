"""Spot-check the chip plan against live data.

Usage: PYTHONPATH=. python -m scripts.spotcheck_chip_plan <entry_id> [horizon]
"""
import json
import sys

from api.chat import _build_context_for_entry
from api.chips import _get_entry_chips, _resolve_current_gw
from src import config
from src.chip_advisor import build_chip_plan


def main():
    entry_id = int(sys.argv[1])
    horizon = int(sys.argv[2]) if len(sys.argv) > 2 else getattr(config, "CHIP_PLAN_HORIZON_GWS", 8)
    current_gw = _resolve_current_gw()
    ctx = _build_context_for_entry(entry_id, current_gw, horizon=horizon)
    plan = build_chip_plan(
        squad=ctx["squad"], current_gw=current_gw,
        gw_projections=ctx["gw_projections"],
        chips_played=_get_entry_chips(entry_id),
        itb_m=float(ctx["bank_m"]), fixtures=ctx.get("fixtures"),
        horizon_gws=horizon,
    )
    print(json.dumps(plan, indent=2, default=str))
    print("\n--- summary ---")
    for r in plan["recommendations"]:
        tag = "PROVISIONAL" if r["provisional"] else f"+{r['ev_gain']} xPts"
        print(f"{r['chip']:16s} GW{r['event_id']:<3d} {tag}")
    if plan["nudge"]:
        print(f"NUDGE: {plan['nudge']['chip']} this GW (+{plan['nudge']['ev_gain']})")


if __name__ == "__main__":
    main()
