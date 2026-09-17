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
    print("signals:", plan.get("signals"))
    for r in plan["recommendations"]:
        if r["provisional"]:
            lik = r.get("likelihood")
            tag = "PROVISIONAL" + (f" (~{lik:.0%} likely)" if lik is not None and lik < 1 else "")
        else:
            tag = f"+{r['ev_gain']} xPts"
        print(f"{r['chip']:16s} GW{r['event_id']:<3d} {tag}")
        d = r.get("distribution")
        if d:
            print(f"{'':16s}       beats bar {d.get('p_beats_bar', 0):.0%} · return {d['p_return']:.0%}"
                  f" · haul {d['p_haul']:.0%} · blank {d['p_blank']:.0%}"
                  f" · modal {d['modal']} · 80% band {d['p80_low']}-{d['p80_high']}")
        for reason in r["reasons"]:
            if reason.startswith("Risk:") or "European" in reason or "League" in reason:
                print(f"{'':16s}       {reason}")
    print("--- outlook (hold) ---")
    for o in plan.get("outlook", []):
        if o["status"] != "hold":
            continue
        d = o.get("distribution") or {}
        odds = f" · beats bar {d['p_beats_bar']:.0%}" if "p_beats_bar" in d else ""
        where = f"GW{o['event_id']} +{o['ev_gain']} vs bar {o['bar']}" if o["event_id"] else "no window"
        print(f"{o['chip']:16s} {where}{odds}")
    if plan["nudge"]:
        n = plan["nudge"]
        odds = f", {n['p_beats_bar']:.0%} beats bar" if "p_beats_bar" in n else ""
        print(f"NUDGE: {n['chip']} this GW (+{n['ev_gain']}{odds})")
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
