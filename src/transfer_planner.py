"""Horizon transfer planner for the squad picker.

Given a 15-man squad and per-GW projections (``xpts_gw{N}`` columns), sequence
transfers across the fixture horizon under the real FPL rules: 1 free transfer
accrues per GW (banked up to a cap), each GW you either USE free transfers on
the best like-for-like swaps or ROLL to accumulate, and an extra transfer costs
a -4 hit (taken only when its remaining-horizon gain beats the 4-point cost).

Policy is greedy-per-GW: take value early (a point this GW is worth more than
the same point next GW), roll when nothing clears the bar. A transfer's gain is
scored on the REMAINING horizon (this GW onward), so making it earlier is worth
more -- which is what makes roll-vs-use fall out naturally.

Pure/data-only: operates on a projections DataFrame, no network. Selling price
is approximated by current price (purchase price isn't tracked here).
"""
import pandas as pd

from . import config

MAX_PER_TEAM = 3


def _num(v, default=0.0):
    n = pd.to_numeric(v, errors="coerce")
    return default if pd.isna(n) else float(n)


def _red_flag(r):
    """True when a player is a likely-unavailable transfer target: an injury/
    suspension/unavailable status, or a next-round playing chance at/below the
    configured floor (e.g. 0 == ruled out). Missing status/chance columns
    resolve to "available" -- never force a sell on data we don't have."""
    statuses = {
        str(s).lower() for s in getattr(config, "TRANSFER_PLANNER_RED_FLAG_STATUSES", ("i", "s", "u"))
    }
    max_chance = getattr(config, "TRANSFER_PLANNER_RED_FLAG_MAX_CHANCE", 0.0)
    status = str(r.get("status") or "a").lower()
    chance = r.get("chance_of_playing_next_round")
    try:
        chance = float(chance)
    except (TypeError, ValueError):
        chance = None
    return status in statuses or (chance is not None and chance <= max_chance)


def _build_info(proj, gws):
    df = proj.drop_duplicates("id")
    info = {}
    for _, r in df.iterrows():
        pid = int(r["id"])
        info[pid] = {
            "id": pid,
            "name": r.get("web_name"),
            "pos": r.get("pos"),
            "team": str(r.get("team_short") or "?"),
            "price": _num(r.get("price_m")),
            "xg": {g: _num(r.get(f"xpts_gw{g}")) for g in gws},
            "red_flag": _red_flag(r),
        }
    return info


def _horizon(info, pid, remaining):
    xg = info[pid]["xg"]
    return sum(xg.get(g, 0.0) for g in remaining)


def _xi_floors(squad, info, hz):
    """Likely XI (top 11 by remaining-horizon value) and its weakest member
    per position / overall — the bar an incoming player must beat to turn a
    bench slot into real points."""
    xi_ids = set(sorted(squad, key=lambda p: hz.get(p, 0.0), reverse=True)[:11])
    by_pos, overall = {}, None
    for pid in xi_ids:
        v, pos = hz.get(pid, 0.0), info[pid]["pos"]
        by_pos[pos] = min(by_pos.get(pos, v), v)
        overall = v if overall is None else min(overall, v)
    return xi_ids, by_pos, (overall or 0.0)


def _best_swap(squad, info, unowned, hz, bank, team_counts, xi=None):
    """Best single like-for-like swap: maximizes remaining-horizon gain subject
    to budget and the 3-per-club cap. Returns {sell, buy, pos, gain} or None.

    With `xi` (from _xi_floors), a bench seller's swap only counts the points
    the buyer would add by displacing the weakest same-position XI member —
    upgrading a player who stays on the bench is worth nothing."""
    xi_ids, xi_min_by_pos, xi_min_overall = xi if xi else (None, None, None)
    best = None
    for s in squad:
        si = info[s]
        s_hz, s_price, s_team, s_pos = hz[s], si["price"], si["team"], si["pos"]
        budget = bank + s_price
        for b in unowned:
            bi = info[b]
            if bi["pos"] != s_pos:
                continue
            if bi["price"] > budget + 1e-9:
                continue
            bt = bi["team"]
            count_after = team_counts.get(bt, 0) - (1 if bt == s_team else 0)
            if count_after + 1 > MAX_PER_TEAM:
                continue
            if xi_ids is not None and s not in xi_ids:
                floor = xi_min_by_pos.get(s_pos, xi_min_overall)
                gain = max(0.0, hz[b] - floor)
            else:
                gain = hz[b] - s_hz
            if best is None or gain > best["gain"]:
                best = {"sell": s, "buy": b, "pos": s_pos, "gain": gain}
    return best


def _move_record(m, info):
    s, b = info[m["sell"]], info[m["buy"]]
    rec = {
        "position": m["pos"],
        "sell": {"id": s["id"], "name": s["name"], "team": s["team"], "price": round(s["price"], 1)},
        "buy": {"id": b["id"], "name": b["name"], "team": b["team"], "price": round(b["price"], 1)},
        "score_gain": round(m["gain"], 2),
    }
    if m.get("forced_injury"):
        rec["forced_injury"] = True
    return rec


def _note(moves, ft_before, info):
    if not moves:
        return f"Roll — no move above the bar; bank the free transfer (had {ft_before})."
    parts = [f"{info[m['sell']]['name']} → {info[m['buy']]['name']} (+{round(m['gain'], 1)})"
             for m in moves]
    return "; ".join(parts)


def plan_transfers(proj, squad_ids, gws, itb_m=0.0, start_ft=1, ft_cap=5,
                   hit_penalty=4.0, allow_hits=True, min_gain=2.0, max_moves_per_gw=3):
    info = _build_info(proj, gws)
    squad = set(int(x) for x in squad_ids if int(x) in info)
    bank = float(itb_m)
    ft = int(start_ft)
    plan, total_net = [], 0.0

    # Injury gate: a red-flagged player in the LIKELY first-GW XI (top 11 of
    # the squad by that GW's projection) gets force-sold ahead of the normal
    # greedy decision, bypassing min_gain -- an "i"/"s"/"u" status or a 0%
    # playing chance means the projection itself is close to meaningless, so
    # the usual gain threshold doesn't apply. Bench red flags don't force.
    first_gw = gws[0] if gws else None
    likely_xi = set()
    if first_gw is not None:
        by_first_gw = sorted(squad, key=lambda pid: info[pid]["xg"].get(first_gw, 0.0), reverse=True)
        likely_xi = set(by_first_gw[:11])
    forced_sells = {pid for pid in likely_xi if info[pid].get("red_flag")}

    for gi, g in enumerate(gws):
        if gi > 0:
            ft = min(ft_cap, ft + 1)  # accrue a free transfer each new GW
        ft_before = ft
        remaining = gws[gi:]
        hz = {pid: _horizon(info, pid, remaining) for pid in info}
        xi = (_xi_floors(squad, info, hz)
              if bool(getattr(config, "TRANSFER_PLAN_XI_AWARE", True)) else None)
        team_counts = {}
        for pid in squad:
            t = info[pid]["team"]
            team_counts[t] = team_counts.get(t, 0) + 1

        moves, hits = [], 0

        if gi == 0:
            for pid in sorted(forced_sells, key=lambda p: info[p]["xg"].get(g, 0.0)):
                if pid not in squad or len(moves) >= max_moves_per_gw or len(moves) >= ft:
                    break
                unowned = [x for x in info if x not in squad]
                best = _best_swap({pid}, info, unowned, hz, bank, team_counts)
                if best is None:
                    continue
                s, b = best["sell"], best["buy"]
                squad.discard(s)
                squad.add(b)
                bank += info[s]["price"] - info[b]["price"]
                team_counts[info[s]["team"]] = team_counts.get(info[s]["team"], 0) - 1
                team_counts[info[b]["team"]] = team_counts.get(info[b]["team"], 0) + 1
                best["forced_injury"] = True
                moves.append(best)

        pos_mult = getattr(config, "TRANSFER_PLAN_POS_GAIN_MULT", {}) or {}
        while len(moves) < max_moves_per_gw:
            within_ft = len(moves) < ft
            if not within_ft and not allow_hits:
                break
            threshold = min_gain if within_ft else hit_penalty
            unowned = [pid for pid in info if pid not in squad]
            # Positional bar: the best raw swap may be a GKP/DEF trade that
            # fails its (higher) bar while a slightly smaller MID/FWD gain
            # passes its own — so retry with the failing position excluded
            # instead of giving up on the first miss.
            pool = set(squad)
            best = None
            while pool:
                cand = _best_swap(pool, info, unowned, hz, bank, team_counts, xi=xi)
                if cand is None:
                    break
                bar = threshold * float(pos_mult.get(cand["pos"], 1.0))
                if cand["gain"] > bar:
                    best = cand
                    break
                pool = {pid for pid in pool if info[pid]["pos"] != cand["pos"]}
            if best is None:
                break
            s, b = best["sell"], best["buy"]
            squad.discard(s)
            squad.add(b)
            bank += info[s]["price"] - info[b]["price"]
            team_counts[info[s]["team"]] = team_counts.get(info[s]["team"], 0) - 1
            team_counts[info[b]["team"]] = team_counts.get(info[b]["team"], 0) + 1
            if not within_ft:
                hits += 1
            moves.append(best)

        used = len(moves)
        hit_cost = hits * hit_penalty
        gw_gain = round(sum(m["gain"] for m in moves), 2)
        net = round(gw_gain - hit_cost, 2)
        total_net += net
        ft_after = ft_before if used == 0 else max(0, ft_before - min(used, ft_before))
        plan.append({
            "gw": g,
            "action": "roll" if used == 0 else "transfer",
            "free_transfers_before": ft_before,
            "free_transfers_after": ft_after,
            "hits": hits,
            "hit_cost": round(hit_cost, 2),
            "gw_gain": gw_gain,
            "net_gain": net,
            "bank_after": round(bank, 2),
            "moves": [_move_record(m, info) for m in moves],
            "note": _note(moves, ft_before, info),
        })
        ft = ft_after

    verdict, reasoning = _verdict_and_reasoning(plan, min_gain, ft_cap)

    return {
        "gws": list(gws),
        "horizon_gws": len(gws),
        "start_free_transfers": int(start_ft),
        "ft_cap": int(ft_cap),
        "allow_hits": bool(allow_hits),
        "hit_penalty": float(hit_penalty),
        "total_net_gain": round(total_net, 2),
        "final_bank": round(bank, 2),
        "plan": plan,
        "verdict": verdict,
        "reasoning": reasoning,
        "first_gw_ft_before": plan[0]["free_transfers_before"] if plan else int(start_ft),
        "first_gw_ft_after": (
            min(int(ft_cap), plan[0]["free_transfers_before"] + 1)
            if plan and plan[0]["action"] == "roll"
            else plan[0]["free_transfers_after"] if plan else int(start_ft)
        ),
    }


def _verdict_and_reasoning(plan, min_gain, ft_cap):
    """Top-level verdict for the first horizon GW: an injury-forced sell always
    wins (it isn't optional), otherwise it's whichever the greedy walk chose
    (spend now vs roll the FT), with a plain-English reason a user can act on."""
    first = plan[0] if plan else None
    forced_moves = [m for m in first["moves"] if m.get("forced_injury")] if first else []
    if forced_moves:
        flagged = ", ".join(m["sell"]["name"] for m in forced_moves)
        reasoning = (f"Flagged player ({flagged}) in your likely XI -- replacing "
                     f"them takes priority over rolling, even below the usual gain bar.")
        return "spend_forced_injury", reasoning

    if first and first["action"] == "transfer":
        names = ", ".join(f"{m['sell']['name']} -> {m['buy']['name']}" for m in first["moves"])
        if first.get("hits"):
            # Quote what the user actually banks — the raw sum before hit
            # costs reads as a bigger promise than the plan delivers.
            reasoning = (f"Move now: {names} (net +{first['net_gain']} xPts "
                         f"after -{first['hit_cost']:g} in hits; bar {min_gain}).")
        else:
            reasoning = f"Move now: {names} (+{first['gw_gain']} xPts >= {min_gain} threshold)."
        return "spend", reasoning

    if first:
        nxt = next((p for p in plan[1:] if p["action"] == "transfer"), None)
        follow = (f" -- GW{nxt['gw']} the plan makes {len(nxt['moves'])} move(s) for +{nxt['gw_gain']}."
                  if nxt else ".")
        reasoning = (f"No move gains >= {min_gain} xPts this GW. Roll the FT "
                     f"({first['free_transfers_before']}->"
                     f"{min(int(ft_cap), first['free_transfers_before'] + 1)}){follow}")
        return "roll", reasoning

    return "roll", "No horizon GWs."
