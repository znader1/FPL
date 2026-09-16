"""Make the multi-GW plan's first-GW moves the applyable moves.

`build_recommendations` emits two transfer views: the single-GW beam list
(`transfers.moves`, which the frontend's Apply buttons step through via
`squad_with_transfers_steps`) and the multi-GW plan (`transfer_plan_horizon`,
the actual recommendation). Putting the plan's first-GW moves at the front of
the beam list makes "Apply" apply the recommendation; the beam survivors follow
as alternatives. Pure, no network, never raises on malformed input.
"""


def _pair(m):
    try:
        return int(m["sell"]["id"]), int(m["buy"]["id"])
    except (KeyError, TypeError, ValueError):
        return None


def _as_beam_move(m):
    return {
        "position": m.get("position"),
        "sell": dict(m["sell"]),
        "buy": dict(m["buy"]),
        "score_gain": round(float(m.get("horizon_gain", 0.0)), 2),
    }


def merge_plan_moves_into_preview(preview, plan_horizon):
    """Mutates and returns `preview`. Every move gets `in_plan`; on a spend
    verdict the plan's first-GW moves lead the list (deduplicated by
    sell/buy pair, reusing the beam record when one matches so its hot/set-piece
    enrichment survives)."""
    if not isinstance(preview, dict):
        return preview
    beam = [m for m in (preview.get("moves") or []) if isinstance(m, dict)]
    for m in beam:
        m.setdefault("in_plan", False)
    preview["moves"] = beam

    detail = (plan_horizon or {}).get("verdict_detail") if isinstance(plan_horizon, dict) else None
    if not isinstance(detail, dict) or detail.get("action") not in ("spend", "spend_forced_injury"):
        return preview

    beam_by_pair = {_pair(m): m for m in beam}
    plan_moves, plan_pairs = [], set()
    for pm in detail.get("moves") or []:
        pair = _pair(pm) if isinstance(pm, dict) else None
        if pair is None or pair in plan_pairs:
            continue
        base = beam_by_pair.get(pair)
        mv = dict(base) if base else _as_beam_move(pm)
        mv["in_plan"] = True
        mv["this_gw_gain"] = round(float(pm.get("this_gw_gain", 0.0)), 2)
        plan_moves.append(mv)
        plan_pairs.add(pair)
    if not plan_moves:
        return preview

    merged = plan_moves + [m for m in beam if _pair(m) not in plan_pairs]
    preview["moves"] = merged

    by_pos = {}
    for m in merged:
        pos = m.get("position") or "UNK"
        by_pos[pos] = by_pos.get(pos, 0) + 1
    preview["moves_by_position"] = by_pos

    tp = preview.get("transfer_plan")
    if isinstance(tp, dict):
        tp["transfer_count_built"] = len(merged)

    first = next((p for p in (plan_horizon.get("plan") or []) if isinstance(p, dict)), None)
    if first is not None and first.get("bank_after") is not None:
        try:
            preview["remaining_itb"] = round(float(first["bank_after"]), 1)
        except (TypeError, ValueError):
            pass
    return preview
