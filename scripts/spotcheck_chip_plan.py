"""Spot-check the chip plan against live data.

Usage: PYTHONPATH=. python -m scripts.spotcheck_chip_plan <entry_id> [horizon]
"""
import json
import sys

from api.chat import _build_context_for_entry
from api.chips import SIGNAL_KEYS, _get_entry_chips, _resolve_current_gw, build_chip_signals
from api.main import get_bootstrap_cached
from src import config
from src.chip_advisor import build_chip_plan


def main():
    entry_id = int(sys.argv[1])
    horizon = int(sys.argv[2]) if len(sys.argv) > 2 else getattr(config, "CHIP_PLAN_HORIZON_GWS", 8)
    current_gw = _resolve_current_gw()
    ctx = _build_context_for_entry(entry_id, current_gw, horizon=horizon)

    # Same signal-building approach as api/chips.py::_build_plan_response —
    # shared via build_chip_signals so the two never drift out of sync.
    # Fail-soft: a signals failure must never block the spot-check.
    signals = {}
    try:
        bootstrap = get_bootstrap_cached()
        signals = build_chip_signals(bootstrap, current_gw, horizon)
    except Exception as e:  # noqa: BLE001 - signals must never fail the spot-check
        signals = {}
        print(f"WARNING: chip strategy signals unavailable: {e}", file=sys.stderr)

    plan = build_chip_plan(
        squad=ctx["squad"], current_gw=current_gw,
        gw_projections=ctx["gw_projections"],
        chips_played=_get_entry_chips(entry_id),
        itb_m=float(ctx["bank_m"]), fixtures=ctx.get("fixtures"),
        horizon_gws=horizon,
        **{k: signals.get(k) for k in SIGNAL_KEYS},
    )
    print(json.dumps(plan, indent=2, default=str))
    print("\n--- summary ---")
    for r in plan["recommendations"]:
        tag = "PROVISIONAL" if r["provisional"] else f"+{r['ev_gain']} xPts"
        print(f"{r['chip']:16s} GW{r['event_id']:<3d} {tag}")
    if plan["nudge"]:
        print(f"NUDGE: {plan['nudge']['chip']} this GW (+{plan['nudge']['ev_gain']})")
    print("\n--- calendar (model zone) ---")
    for row in plan.get("calendar", []):
        if not row["in_model_zone"]:
            continue
        flags = []
        if row["post_break"]:
            flags.append("post-break")
        if row["has_dgw"]:
            flags.append("DGW")
        if row["is_blank_heavy"]:
            flags.append("BGW")
        if row["squad_european"]:
            flags.append(f"{len(row['squad_european'])} in Europe")
        if row["cup_clash"]:
            flags.append(f"cup: {row['cup_clash']['label']}")
        print(f"GW{row['gw']:<3d} {', '.join(flags) or '-'}")


if __name__ == "__main__":
    main()
